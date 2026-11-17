# Agentic Docs Assistant

[![CI](https://github.com/linusdominic/agentic-docs-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/linusdominic/agentic-docs-assistant/actions/workflows/ci.yml)

A support agent that answers questions from a product's documentation and files a ticket when the docs are not enough. It is a small, complete example of a production-shaped agent service:

- **LangGraph** runs the agent loop, pauses for human approval, and resumes.
- **PostgreSQL + pgvector** stores document embeddings, tickets, and every conversation's state.
- **FastAPI** exposes the agent over HTTP, with token streaming.
- **Docker** packages it for **Google Cloud Run** and Cloud SQL.

The sample knowledge base is the documentation of a fictional note-taking app, Nimbus Notes. Swap in your own Markdown files and the agent answers from those instead.

## How it works

```mermaid
flowchart LR
    U[Client] -->|POST /chat| A[FastAPI]
    A --> G

    subgraph G[LangGraph agent]
        direction LR
        M[model] -->|tool call| T[tools]
        T --> M
    end

    T -->|search_docs| V[(pgvector<br/>chunks)]
    T -->|create_ticket<br/>after approval| K[(tickets)]
    G <-->|checkpoint<br/>every step| C[(conversation<br/>state)]
    M <--> L[LLM provider]

    subgraph P[PostgreSQL]
        V
        K
        C
    end
```

1. **Ingestion** splits each document into heading-aware chunks, embeds them locally, and stores them in a `vector` column with an HNSW index.
2. **A chat request** enters the graph. The model decides whether to call a tool. `search_docs` embeds the question and returns the closest chunks, each labelled with its source file. The model answers from those passages and cites the files.
3. **Actions need approval.** When the model calls `create_ticket`, the graph pauses with an interrupt and the API returns `needs_approval`. Nothing is written until the client calls `/chat/approve`.
4. **State lives in Postgres.** A checkpoint is saved after every step, keyed by `thread_id`. That gives the agent memory across requests, lets a paused run resume later, and means the API holds no state of its own, so it can scale out or restart freely.

## Quick start

You need [uv](https://docs.astral.sh/uv/), Docker, and an API key for a chat model.

```bash
git clone https://github.com/linusdominic/agentic-docs-assistant.git
cd agentic-docs-assistant
cp .env.example .env        # then set ANTHROPIC_API_KEY in .env

make install                # install dependencies
make db                     # PostgreSQL + pgvector on localhost:5433
make ingest                 # chunk, embed and store the sample docs
make dev                    # API on http://localhost:8000
```

Interactive API docs are at <http://localhost:8000/docs>.

To run everything in containers instead, use `make up`.

### Choosing a model

`LLM_MODEL` takes any LangChain chat model string in the form `provider:model`, so switching providers is a configuration change. The default is `anthropic:claude-opus-5-5`. For a Google-hosted model on Vertex AI, install `langchain-google-vertexai` and set a `google_vertexai:` model.

Embeddings run locally with [fastembed](https://github.com/qdrant/fastembed) (`BAAI/bge-small-en-v1.5`, 384 dimensions), so ingestion and retrieval need no API key.

## Using the API

Ask a question:

```bash
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message": "Can I get a refund on a yearly plan?"}'
```

```json
{
  "thread_id": "3f6c0d5e9a1b4c7d8e2f0a1b2c3d4e5f",
  "status": "complete",
  "reply": "Yes. You can request a refund within 30 days of your first payment ... (source: billing.md)",
  "sources": ["billing.md"],
  "pending_action": null
}
```

Send the same `thread_id` to continue the conversation.

Ask for something the agent has to act on, and it stops for approval:

```bash
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message": "Sync fails with S-401 even after signing in again. Please contact support."}'
```

```json
{
  "thread_id": "9b1e…",
  "status": "needs_approval",
  "reply": null,
  "sources": ["troubleshooting.md"],
  "pending_action": {
    "action": "create_ticket",
    "title": "Sync fails with S-401 after re-login",
    "description": "…"
  }
}
```

Approve or decline it:

```bash
curl -s localhost:8000/chat/approve -H 'content-type: application/json' \
  -d '{"thread_id": "9b1e…", "approved": true}'
```

Stream a reply as server-sent events:

```bash
curl -N localhost:8000/chat/stream -H 'content-type: application/json' \
  -d '{"message": "What are the API rate limits?"}'
```

```
event: tool_call
data: {"name": "search_docs", "args": {"query": "API rate limits"}}

event: token
data: {"text": "Each token can make "}

event: done
data: {"thread_id": "…", "status": "complete"}
```

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness check |
| `POST /chat` | Send a message, wait for the full reply |
| `POST /chat/stream` | Send a message, receive `tool_call`, `token`, `approval_required`, `error` and `done` events |
| `POST /chat/approve` | Approve or decline the action a paused thread is waiting on |

Set `API_KEY` to require an `X-API-Key` header on the chat routes.

## Project layout

```
src/docs_agent/
  agent.py       LangGraph graph: model <-> tools loop, system prompt
  tools.py       search_docs (retrieval) and create_ticket (approval-gated action)
  api.py         FastAPI app: chat, streaming, approvals, API-key check
  db.py          Connection pool, schema, vector store, ticket store
  ingest.py      Ingestion CLI: read -> chunk -> embed -> store
  chunking.py    Heading-aware Markdown splitter
  embeddings.py  Local embedding model
  config.py      Settings from environment variables
knowledge_base/  Sample documents
tests/           Unit tests and PostgreSQL integration tests
deploy/          Cloud Run deployment script and guide
```

## Tests

```bash
make test               # unit tests: no database, network or API key
make test-integration   # adds the tests that run against PostgreSQL + pgvector
make lint
```

The unit tests drive the real graph and the real FastAPI app with a scripted chat model and in-memory stores, so they cover tool calling, per-thread memory, the approval flow, and streaming without calling a model provider. The integration tests ingest the sample documents into pgvector and check that retrieval returns the right file for a set of questions, and that a conversation saved by one process is readable by another. CI runs both on every push.

## Deploying to Cloud Run

The same container runs on Cloud Run with Cloud SQL for PostgreSQL. See [deploy/README.md](deploy/README.md) for the setup and [deploy/cloudrun.sh](deploy/cloudrun.sh) for the deploy command.

## Design notes

- **One database for three jobs.** Vectors, application data and agent state all sit in PostgreSQL. That is one service to run, back up and secure, and it is enough until the corpus reaches many millions of chunks.
- **Tools are built around interfaces.** `make_tools` takes a retriever and a ticket store, so tests pass in fakes and a different backend can be swapped in without touching the agent.
- **Approval is part of the graph, not the client.** The interrupt is raised inside the tool, so no caller can skip it, and the pending action survives a restart because it is checkpointed.
- **The API is stateless.** Any instance can serve any request for any thread, which is what lets Cloud Run add and remove instances under load.

## Limitations

- Ingestion handles Markdown and plain text only, and re-embeds a whole file when it changes.
- Retrieval is vector-only. Hybrid search (adding PostgreSQL full-text) and reranking would help on larger corpora.
- There are no user accounts: anyone with the API key can read a thread if they know its id.
- Long agent runs hold the HTTP request open. A queue-backed worker is the next step for longer tasks.

## License

MIT
