"""The agent itself: a LangGraph loop between the model and its tools."""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

SYSTEM_PROMPT = """\
You are the support assistant for Nimbus Notes, a note-taking app.

Answer questions about the product from its documentation. Call search_docs before \
answering anything about how the product works, its plans, limits or troubleshooting, \
and base the answer on the passages it returns. Name the files you relied on, for \
example "(source: billing.md)". If the documentation does not cover the question, say \
so plainly instead of guessing.

When the documentation cannot solve the user's problem, or the user asks to reach a \
person, offer to file a support ticket with create_ticket. Write a short title and a \
description with the details a support engineer would need. The user approves each \
ticket before it is filed, so tell them the outcome afterwards.

Keep answers short and practical."""


def build_graph(
    llm: BaseChatModel,
    tools: list[BaseTool],
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Wire the agent loop: model -> (tools -> model)* -> end.

    The checkpointer saves the conversation after every step, keyed by thread_id, which is
    what gives the agent memory across requests and lets a paused run resume later.
    """
    llm_with_tools = llm.bind_tools(tools)

    async def call_model(state: MessagesState) -> dict[str, list[AnyMessage]]:
        messages = [SystemMessage(SYSTEM_PROMPT), *state["messages"]]
        return {"messages": [await llm_with_tools.ainvoke(messages)]}

    graph = StateGraph(MessagesState)
    graph.add_node("model", call_model)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "model")
    # If the model asked for a tool, run it; otherwise the turn is finished.
    graph.add_conditional_edges("model", tools_condition)
    graph.add_edge("tools", "model")
    return graph.compile(checkpointer=checkpointer)
