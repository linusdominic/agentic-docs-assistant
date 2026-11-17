"""HTTP API for the agent: request/response chat, token streaming, and approvals."""

import json
import logging
import os
import re
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pydantic import BaseModel, Field

from docs_agent import __version__
from docs_agent.config import Settings, get_settings

logger = logging.getLogger(__name__)

_SOURCE_TAG = re.compile(r"\[source: ([^\]]+)\]")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    thread_id: str | None = Field(
        default=None, description="Send the same id to continue a conversation."
    )


class ApprovalRequest(BaseModel):
    thread_id: str
    approved: bool


class ChatResponse(BaseModel):
    thread_id: str
    status: Literal["complete", "needs_approval"]
    reply: str | None = None
    sources: list[str] = []
    pending_action: dict[str, Any] | None = None


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _current_turn(messages: list[AnyMessage]) -> list[AnyMessage]:
    """The messages produced since the user last spoke."""
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index + 1 :]
    return messages


def _to_response(thread_id: str, result: dict[str, Any]) -> ChatResponse:
    turn = _current_turn(result.get("messages", []))
    sources = sorted(
        {
            match
            for message in turn
            if isinstance(message, ToolMessage)
            for match in _SOURCE_TAG.findall(str(message.content))
        }
    )
    interrupts = result.get("__interrupt__")
    if interrupts:
        return ChatResponse(
            thread_id=thread_id,
            status="needs_approval",
            sources=sources,
            pending_action=interrupts[0].value,
        )
    reply = next((m.text for m in reversed(turn) if isinstance(m, AIMessage) and m.text), None)
    return ChatResponse(thread_id=thread_id, status="complete", reply=reply, sources=sources)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _event_stream(
    graph: CompiledStateGraph, graph_input: Any, thread_id: str
) -> AsyncIterator[str]:
    """Translate a graph run into server-sent events."""
    status = "complete"
    try:
        async for mode, payload in graph.astream(
            graph_input, _config(thread_id), stream_mode=["messages", "updates"]
        ):
            if mode == "messages":
                chunk, metadata = payload
                if (
                    isinstance(chunk, AIMessage)
                    and metadata.get("langgraph_node") == "model"
                    and chunk.text
                ):
                    yield _sse("token", {"text": chunk.text})
            elif "__interrupt__" in payload:
                status = "needs_approval"
                yield _sse("approval_required", payload["__interrupt__"][0].value)
            elif "model" in payload:
                for message in payload["model"]["messages"]:
                    for call in getattr(message, "tool_calls", []):
                        yield _sse("tool_call", {"name": call["name"], "args": call["args"]})
    except Exception as exc:  # the response has already started, so report in-band
        logger.exception("Agent run failed for thread %s", thread_id)
        yield _sse("error", {"message": f"The agent run failed ({type(exc).__name__})."})
        status = "error"
    yield _sse("done", {"thread_id": thread_id, "status": status})


async def _build_resources(settings: Settings) -> tuple[CompiledStateGraph, Any]:
    """Create the production graph and the pool it depends on."""
    from langchain.chat_models import init_chat_model
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from docs_agent.agent import build_graph
    from docs_agent.db import PgVectorStore, TicketStore, create_pool, init_schema
    from docs_agent.embeddings import FastEmbedEmbedder
    from docs_agent.tools import make_tools

    if settings.llm_model.startswith("anthropic:") and not os.environ.get("ANTHROPIC_API_KEY"):
        logger.warning("ANTHROPIC_API_KEY is not set: chat requests will fail until it is.")

    pool = await create_pool(settings.database_url)
    try:
        await init_schema(pool, settings.embedding_dim)

        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()

        embedder = FastEmbedEmbedder(settings.embedding_model, settings.embedding_dim)
        tools = make_tools(PgVectorStore(pool, embedder), TicketStore(pool), k=settings.retrieval_k)
        llm = init_chat_model(settings.llm_model, max_tokens=settings.llm_max_tokens)
        return build_graph(llm, tools, checkpointer), pool
    except BaseException:
        await pool.close()  # otherwise the pool's workers keep a failed startup alive
        raise


def create_app(
    graph: CompiledStateGraph | None = None, settings: Settings | None = None
) -> FastAPI:
    """Application factory. Pass a prebuilt ``graph`` to run without a database (tests)."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if graph is not None:
            app.state.graph = graph
            yield
            return
        app.state.graph, pool = await _build_resources(settings)
        try:
            yield
        finally:
            await pool.close()

    app = FastAPI(
        title="Agentic Docs Assistant",
        version=__version__,
        description="A LangGraph agent with RAG over pgvector and human-approved actions.",
        lifespan=lifespan,
    )

    def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
        if settings.api_key and not secrets.compare_digest(x_api_key or "", settings.api_key):
            raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header.")

    def get_graph(request: Request) -> CompiledStateGraph:
        return request.app.state.graph

    async def require_pending(graph: CompiledStateGraph, thread_id: str) -> None:
        state = await graph.aget_state(_config(thread_id))
        if not any(task.interrupts for task in state.tasks):
            raise HTTPException(
                status_code=409, detail="This thread has no action awaiting approval."
            )

    async def reject_if_pending(graph: CompiledStateGraph, thread_id: str) -> None:
        state = await graph.aget_state(_config(thread_id))
        if any(task.interrupts for task in state.tasks):
            raise HTTPException(
                status_code=409,
                detail="This thread is waiting for an approval. Call /chat/approve first.",
            )

    async def run_agent(
        graph: CompiledStateGraph, graph_input: Any, thread_id: str
    ) -> ChatResponse:
        try:
            result = await graph.ainvoke(graph_input, _config(thread_id))
        except Exception as exc:  # model provider or database failure
            logger.exception("Agent run failed for thread %s", thread_id)
            raise HTTPException(
                status_code=502, detail=f"The agent run failed ({type(exc).__name__})."
            ) from exc
        return _to_response(thread_id, result)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
    async def chat(body: ChatRequest, graph: CompiledStateGraph = Depends(get_graph)):
        """Send a message and wait for the agent's full reply."""
        thread_id = body.thread_id or uuid.uuid4().hex
        await reject_if_pending(graph, thread_id)
        return await run_agent(graph, {"messages": [HumanMessage(body.message)]}, thread_id)

    @app.post("/chat/approve", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
    async def approve(body: ApprovalRequest, graph: CompiledStateGraph = Depends(get_graph)):
        """Approve or decline the action a paused conversation is waiting on."""
        await require_pending(graph, body.thread_id)
        return await run_agent(graph, Command(resume={"approved": body.approved}), body.thread_id)

    @app.post("/chat/stream", dependencies=[Depends(require_api_key)])
    async def chat_stream(body: ChatRequest, graph: CompiledStateGraph = Depends(get_graph)):
        """Send a message and receive the reply as server-sent events, token by token."""
        thread_id = body.thread_id or uuid.uuid4().hex
        await reject_if_pending(graph, thread_id)
        return StreamingResponse(
            _event_stream(graph, {"messages": [HumanMessage(body.message)]}, thread_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
