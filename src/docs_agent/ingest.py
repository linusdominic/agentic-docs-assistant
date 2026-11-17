"""Ingestion half of the RAG pipeline: read files, chunk, embed, store in pgvector."""

import argparse
import asyncio
from pathlib import Path

from docs_agent.chunking import chunk_markdown
from docs_agent.config import get_settings
from docs_agent.db import PgVectorStore, create_pool, init_schema
from docs_agent.embeddings import FastEmbedEmbedder

SUFFIXES = {".md", ".txt"}


async def ingest_directory(store: PgVectorStore, directory: Path, max_chars: int) -> dict[str, int]:
    """Ingest every markdown or text file under ``directory``. Returns chunks per file."""
    counts: dict[str, int] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUFFIXES:
            source = path.relative_to(directory).as_posix()
            chunks = chunk_markdown(path.read_text(encoding="utf-8"), max_chars=max_chars)
            counts[source] = await store.replace_source(source, chunks)
    return counts


async def _run(directory: Path) -> None:
    settings = get_settings()
    pool = await create_pool(settings.database_url)
    try:
        await init_schema(pool, settings.embedding_dim)
        embedder = FastEmbedEmbedder(settings.embedding_model, settings.embedding_dim)
        store = PgVectorStore(pool, embedder)
        counts = await ingest_directory(store, directory, settings.chunk_max_chars)
    finally:
        await pool.close()

    for source, n in counts.items():
        print(f"{source}: {n} chunks")
    print(f"Ingested {sum(counts.values())} chunks from {len(counts)} files.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest documents into the vector store.")
    parser.add_argument("directory", nargs="?", default="knowledge_base", type=Path)
    args = parser.parse_args()
    if not args.directory.is_dir():
        parser.error(f"{args.directory} is not a directory")
    asyncio.run(_run(args.directory))


if __name__ == "__main__":
    main()
