import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from docs_agent.api import create_app
from docs_agent.config import Settings
from tests.conftest import tool_call


def client_for(graph, **settings) -> TestClient:
    return TestClient(create_app(graph=graph, settings=Settings(_env_file=None, **settings)))


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        event, data = block.split("\n", 1)
        events.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


def test_health(make_graph):
    graph, _ = make_graph([])
    with client_for(graph) as client:
        assert client.get("/health").json()["status"] == "ok"


def test_chat_returns_reply_and_sources(make_graph):
    graph, _ = make_graph(
        [tool_call("search_docs", query="refunds"), AIMessage("Refunds within 30 days.")]
    )
    with client_for(graph) as client:
        body = client.post("/chat", json={"message": "refund?"}).json()

    assert body["status"] == "complete"
    assert body["reply"] == "Refunds within 30 days."
    assert body["sources"] == ["billing.md"]
    assert body["thread_id"]


def test_thread_id_continues_a_conversation(make_graph):
    graph, model = make_graph([AIMessage("one"), AIMessage("two")])
    with client_for(graph) as client:
        first = client.post("/chat", json={"message": "a"}).json()
        client.post("/chat", json={"message": "b", "thread_id": first["thread_id"]})

    assert len(model.calls[1]) == 4  # system + a + "one" + b


def test_approval_flow(make_graph, tickets):
    graph, _ = make_graph(
        [tool_call("create_ticket", title="Sync", description="502"), AIMessage("Filed #1.")]
    )
    with client_for(graph) as client:
        paused = client.post("/chat", json={"message": "contact support"}).json()
        assert paused["status"] == "needs_approval"
        assert paused["pending_action"]["title"] == "Sync"
        assert tickets.created == []

        # A new message is refused while an approval is outstanding.
        blocked = client.post("/chat", json={"message": "hello?", "thread_id": paused["thread_id"]})
        assert blocked.status_code == 409

        done = client.post(
            "/chat/approve", json={"thread_id": paused["thread_id"], "approved": True}
        ).json()

    assert done == {
        "thread_id": paused["thread_id"],
        "status": "complete",
        "reply": "Filed #1.",
        "sources": [],
        "pending_action": None,
    }
    assert tickets.created == [("Sync", "502")]


def test_approve_without_pending_action_is_rejected(make_graph):
    graph, _ = make_graph([])
    with client_for(graph) as client:
        response = client.post("/chat/approve", json={"thread_id": "nope", "approved": True})
    assert response.status_code == 409


def test_stream_emits_tool_call_tokens_and_done(make_graph):
    graph, _ = make_graph(
        [tool_call("search_docs", query="refunds"), AIMessage("Refunds within 30 days.")]
    )
    with client_for(graph) as client:
        response = client.post("/chat/stream", json={"message": "refund?", "thread_id": "s1"})

    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert ("tool_call", {"name": "search_docs", "args": {"query": "refunds"}}) in events
    assert "".join(d["text"] for e, d in events if e == "token") == "Refunds within 30 days."
    assert events[-1] == ("done", {"thread_id": "s1", "status": "complete"})


def test_stream_reports_approval_required(make_graph):
    graph, _ = make_graph([tool_call("create_ticket", title="Sync", description="502")])
    with client_for(graph) as client:
        events = parse_sse(client.post("/chat/stream", json={"message": "support"}).text)

    assert events[-2][0] == "approval_required"
    assert events[-2][1]["title"] == "Sync"
    assert events[-1][1]["status"] == "needs_approval"


@pytest.mark.parametrize(
    ("headers", "expected"),
    [({}, 401), ({"X-API-Key": "wrong"}, 401), ({"X-API-Key": "s3cret"}, 200)],
)
def test_api_key_is_enforced_when_configured(make_graph, headers, expected):
    graph, _ = make_graph([AIMessage("hi")])
    with client_for(graph, api_key="s3cret") as client:
        assert client.post("/chat", json={"message": "hi"}, headers=headers).status_code == expected


def test_empty_message_is_rejected(make_graph):
    graph, _ = make_graph([])
    with client_for(graph) as client:
        assert client.post("/chat", json={"message": ""}).status_code == 422


def test_model_failure_becomes_a_502(make_graph):
    graph, _ = make_graph([])  # the scripted model has nothing to say, so the call raises
    with client_for(graph) as client:
        response = client.post("/chat", json={"message": "hi"})

    assert response.status_code == 502
    assert response.json()["detail"] == "The agent run failed (IndexError)."


def test_stream_reports_model_failure_in_band(make_graph):
    graph, _ = make_graph([])
    with client_for(graph) as client:
        events = parse_sse(client.post("/chat/stream", json={"message": "hi"}).text)

    assert events[-2][0] == "error"
    assert events[-1][1]["status"] == "error"
