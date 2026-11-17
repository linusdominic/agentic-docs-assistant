"""Tests against a real PostgreSQL with pgvector.

Skipped unless TEST_DATABASE_URL is set. Run them with ``make test-integration``.
"""

import os
import uuid
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set"
)

KNOWLEDGE_BASE = Path(__file__).parent.parent / "knowledge_base"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384


@pytest.fixture(scope="module")
def embedder():
    from docs_agent.embeddings import FastEmbedEmbedder

    return FastEmbedEmbedder(EMBEDDING_MODEL, EMBEDDING_DIM)


@pytest.fixture
async def pool():
    from docs_agent.db import create_pool, init_schema

    pool = await create_pool(os.environ["TEST_DATABASE_URL"])
    try:
        await init_schema(pool, EMBEDDING_DIM)
        yield pool
    finally:
        await pool.close()


async def test_ingest_then_search_finds_the_right_document(pool, embedder):
    from docs_agent.db import PgVectorStore
    from docs_agent.ingest import ingest_directory

    store = PgVectorStore(pool, embedder)
    counts = await ingest_directory(store, KNOWLEDGE_BASE, max_chars=900)

    assert set(counts) == {"api.md", "billing.md", "getting-started.md", "troubleshooting.md"}
    assert await store.count() == sum(counts.values())

    cases = {
        "How do I get my money back?": "billing.md",
        "My notes will not sync, I see error S-401": "troubleshooting.md",
        "How many API requests can I make per minute?": "api.md",
        "Can I import my notes from Evernote?": "getting-started.md",
    }
    for question, expected_source in cases.items():
        top = (await store.search(question, k=3))[0]
        assert top.source == expected_source, question
        assert 0 < top.score <= 1


async def test_reingesting_a_document_replaces_its_chunks(pool, embedder):
    from docs_agent.db import PgVectorStore

    store = PgVectorStore(pool, embedder)
    source = f"temp-{uuid.uuid4().hex}.md"

    assert await store.replace_source(source, ["alpha", "beta", "gamma"]) == 3
    assert await store.replace_source(source, ["only one now"]) == 1

    async with pool.connection() as conn:
        cursor = await conn.execute("SELECT content FROM chunks WHERE source = %s", (source,))
        assert [row["content"] for row in await cursor.fetchall()] == ["only one now"]
        await conn.execute("DELETE FROM chunks WHERE source = %s", (source,))


async def test_ticket_store_inserts_a_row(pool):
    from docs_agent.db import TicketStore

    ticket_id = await TicketStore(pool).create("Sync fails", "Error S-401 after update")

    async with pool.connection() as conn:
        cursor = await conn.execute("SELECT title FROM tickets WHERE id = %s", (ticket_id,))
        assert (await cursor.fetchone())["title"] == "Sync fails"


async def test_conversation_survives_a_restart(pool, retriever, tickets):
    """State saved by one graph instance is visible to a fresh one, as after a redeploy."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from docs_agent.agent import build_graph
    from docs_agent.tools import make_tools
    from tests.conftest import ScriptedChatModel

    config = {"configurable": {"thread_id": f"it-{uuid.uuid4().hex}"}}
    tools = make_tools(retriever, tickets)

    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    first = build_graph(ScriptedChatModel(responses=[AIMessage("noted")], calls=[]), tools, saver)
    await first.ainvoke({"messages": [HumanMessage("remember the number 42")]}, config)

    model = ScriptedChatModel(responses=[AIMessage("it was 42")], calls=[])
    second = build_graph(model, tools, AsyncPostgresSaver(pool))
    await second.ainvoke({"messages": [HumanMessage("what was the number?")]}, config)

    seen = [m.content for m in model.calls[0] if isinstance(m, HumanMessage | AIMessage)]
    assert seen == ["remember the number 42", "noted", "what was the number?"]
