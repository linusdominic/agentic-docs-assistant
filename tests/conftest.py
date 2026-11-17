"""Test doubles: a scripted chat model and in-memory stores, so tests need no network."""

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from docs_agent.agent import build_graph
from docs_agent.db import Chunk
from docs_agent.tools import make_tools


class ScriptedChatModel(BaseChatModel):
    """Returns pre-written responses in order and records what it was sent."""

    responses: list[AIMessage]
    calls: list[list] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "scripted"


class FakeRetriever:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str, k: int = 4) -> list[Chunk]:
        self.queries.append(query)
        return [Chunk("billing.md", 0, "Refunds are available within 30 days of purchase.", 0.9)]


class FakeTickets:
    def __init__(self) -> None:
        self.created: list[tuple[str, str]] = []

    async def create(self, title: str, description: str) -> int:
        self.created.append((title, description))
        return len(self.created)


def tool_call(name: str, **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{name}"}])


@pytest.fixture
def retriever() -> FakeRetriever:
    return FakeRetriever()


@pytest.fixture
def tickets() -> FakeTickets:
    return FakeTickets()


@pytest.fixture
def make_graph(retriever, tickets):
    """Build an agent graph around a scripted model."""

    def _make(responses: list[AIMessage]):
        model = ScriptedChatModel(responses=list(responses), calls=[])
        graph = build_graph(model, make_tools(retriever, tickets), InMemorySaver())
        return graph, model

    return _make
