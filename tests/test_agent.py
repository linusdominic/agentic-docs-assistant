from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import Command

from tests.conftest import tool_call

CONFIG = {"configurable": {"thread_id": "t1"}}


async def ask(graph, text: str, config=CONFIG):
    return await graph.ainvoke({"messages": [HumanMessage(text)]}, config)


async def test_agent_searches_docs_then_answers(make_graph, retriever):
    graph, model = make_graph(
        [tool_call("search_docs", query="refund policy"), AIMessage("Refunds within 30 days.")]
    )

    result = await ask(graph, "Can I get a refund?")

    assert retriever.queries == ["refund policy"]
    tool_message = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert "[source: billing.md]" in tool_message.content
    assert result["messages"][-1].content == "Refunds within 30 days."
    # The second model call saw the retrieved passage, and the system prompt came first.
    assert isinstance(model.calls[1][0], SystemMessage)
    assert any(isinstance(m, ToolMessage) for m in model.calls[1])


async def test_direct_answer_skips_tools(make_graph, retriever):
    graph, _ = make_graph([AIMessage("Hello!")])

    result = await ask(graph, "hi")

    assert retriever.queries == []
    assert result["messages"][-1].content == "Hello!"


async def test_conversation_is_remembered_per_thread(make_graph):
    graph, model = make_graph([AIMessage("first"), AIMessage("second"), AIMessage("other")])

    await ask(graph, "one")
    await ask(graph, "two")
    await ask(graph, "three", {"configurable": {"thread_id": "t2"}})

    same_thread = [m.content for m in model.calls[1] if isinstance(m, HumanMessage)]
    other_thread = [m.content for m in model.calls[2] if isinstance(m, HumanMessage)]
    assert same_thread == ["one", "two"]
    assert other_thread == ["three"]


async def test_ticket_waits_for_approval_then_is_created(make_graph, tickets):
    graph, _ = make_graph(
        [
            tool_call("create_ticket", title="Sync fails", description="Error 502 on sync"),
            AIMessage("Ticket #1 is filed."),
        ]
    )

    paused = await ask(graph, "Sync is broken, please contact support")

    assert tickets.created == []  # nothing happens until the user approves
    assert paused["__interrupt__"][0].value == {
        "action": "create_ticket",
        "title": "Sync fails",
        "description": "Error 502 on sync",
    }

    result = await graph.ainvoke(Command(resume={"approved": True}), CONFIG)

    assert tickets.created == [("Sync fails", "Error 502 on sync")]
    assert "Created ticket #1" in result["messages"][-2].content
    assert result["messages"][-1].content == "Ticket #1 is filed."


async def test_declined_ticket_is_not_created(make_graph, tickets):
    graph, _ = make_graph(
        [tool_call("create_ticket", title="t", description="d"), AIMessage("Okay, no ticket.")]
    )

    await ask(graph, "open a ticket")
    result = await graph.ainvoke(Command(resume={"approved": False}), CONFIG)

    assert tickets.created == []
    assert "declined" in result["messages"][-2].content
