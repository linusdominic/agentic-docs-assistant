"""PostgreSQL access: connection pool, schema, vector store and ticket store."""

from dataclasses import dataclass

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from docs_agent.embeddings import Embedder

# One statement per entry: the pool prepares every query, and PostgreSQL does not allow
# several commands in one prepared statement.
SCHEMA = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE IF NOT EXISTS chunks (
        id          bigserial PRIMARY KEY,
        source      text NOT NULL,
        chunk_index integer NOT NULL,
        content     text NOT NULL,
        embedding   vector({dim}) NOT NULL,
        UNIQUE (source, chunk_index)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS chunks_embedding_idx
        ON chunks USING hnsw (embedding vector_cosine_ops)
    """,
    """
    CREATE TABLE IF NOT EXISTS tickets (
        id          bigserial PRIMARY KEY,
        title       text NOT NULL,
        description text NOT NULL,
        created_at  timestamptz NOT NULL DEFAULT now()
    )
    """,
)


async def create_pool(database_url: str) -> AsyncConnectionPool:
    """Open a pool whose connections also satisfy LangGraph's Postgres checkpointer."""
    pool = AsyncConnectionPool(
        database_url,
        min_size=1,
        max_size=10,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    return pool


async def init_schema(pool: AsyncConnectionPool, embedding_dim: int) -> None:
    async with pool.connection() as conn:
        for statement in SCHEMA:
            await conn.execute(statement.format(dim=int(embedding_dim)))


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"


@dataclass(frozen=True)
class Chunk:
    source: str
    chunk_index: int
    content: str
    score: float = 0.0


class PgVectorStore:
    """Document chunks and their embeddings, searched by cosine similarity."""

    def __init__(self, pool: AsyncConnectionPool, embedder: Embedder) -> None:
        self._pool = pool
        self._embedder = embedder

    async def replace_source(self, source: str, chunks: list[str]) -> int:
        """Store the chunks of one document, replacing any earlier version of it."""
        vectors = await self._embedder.embed_documents(chunks) if chunks else []
        rows = [
            (source, index, content, _vector_literal(vector))
            for index, (content, vector) in enumerate(zip(chunks, vectors, strict=True))
        ]
        async with self._pool.connection() as conn, conn.transaction():
            await conn.execute("DELETE FROM chunks WHERE source = %s", (source,))
            if rows:
                async with conn.cursor() as cur:
                    await cur.executemany(
                        "INSERT INTO chunks (source, chunk_index, content, embedding) "
                        "VALUES (%s, %s, %s, %s::vector)",
                        rows,
                    )
        return len(rows)

    async def search(self, query: str, k: int = 4) -> list[Chunk]:
        vector = _vector_literal(await self._embedder.embed_query(query))
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                "SELECT source, chunk_index, content, "
                "       1 - (embedding <=> %s::vector) AS score "
                "FROM chunks ORDER BY embedding <=> %s::vector LIMIT %s",
                (vector, vector, k),
            )
            return [Chunk(**row) for row in await cursor.fetchall()]

    async def count(self) -> int:
        async with self._pool.connection() as conn:
            cursor = await conn.execute("SELECT count(*) AS n FROM chunks")
            return (await cursor.fetchone())["n"]


class TicketStore:
    """Support tickets the agent files on a user's behalf."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def create(self, title: str, description: str) -> int:
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                "INSERT INTO tickets (title, description) VALUES (%s, %s) RETURNING id",
                (title, description),
            )
            return (await cursor.fetchone())["id"]
