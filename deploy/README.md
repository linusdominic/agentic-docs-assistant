# Deploying to Google Cloud Run

The container in the repository root is what runs in production: Cloud Run hosts the API and Cloud SQL for PostgreSQL holds the vectors, tickets and conversation state.

> This deployment path is a reference. The container is built and run locally and in Docker Compose, but the `gcloud` commands below have not been run against a live project from this repository.

## One-time setup

```bash
export PROJECT_ID=my-project REGION=europe-west1 SQL_INSTANCE=docs-agent-db

gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  secretmanager.googleapis.com cloudbuild.googleapis.com --project "$PROJECT_ID"

# PostgreSQL. Cloud SQL ships the pgvector extension; the app enables it on startup.
gcloud sql instances create "$SQL_INSTANCE" --project "$PROJECT_ID" --region "$REGION" \
  --database-version POSTGRES_17 --edition ENTERPRISE --tier db-f1-micro
gcloud sql databases create docs_agent --instance "$SQL_INSTANCE" --project "$PROJECT_ID"
gcloud sql users set-password postgres --instance "$SQL_INSTANCE" --project "$PROJECT_ID" --prompt-for-password
```

Store the three secrets. Cloud Run reaches Cloud SQL through a Unix socket, so the database URL has no host before the slash:

```bash
printf 'postgresql://postgres:PASSWORD@/docs_agent?host=/cloudsql/%s:%s:%s' \
  "$PROJECT_ID" "$REGION" "$SQL_INSTANCE" |
  gcloud secrets create docs-agent-database-url --data-file=- --project "$PROJECT_ID"

printf '%s' "$ANTHROPIC_API_KEY" |
  gcloud secrets create anthropic-api-key --data-file=- --project "$PROJECT_ID"

openssl rand -hex 24 |
  gcloud secrets create docs-agent-api-key --data-file=- --project "$PROJECT_ID"
```

Give the Cloud Run service account the `Secret Manager Secret Accessor` and `Cloud SQL Client` roles.

## Deploy

```bash
./deploy/cloudrun.sh
```

The script builds the image with Cloud Build, deploys it, and prints the service URL.

## Ingest documents

Run ingestion from your machine through the Cloud SQL Auth Proxy, pointing `DATABASE_URL` at the proxy:

```bash
cloud-sql-proxy "$PROJECT_ID:$REGION:$SQL_INSTANCE" --port 5434 &
DATABASE_URL=postgresql://postgres:PASSWORD@localhost:5434/docs_agent uv run docs-agent-ingest knowledge_base
```

## Notes for production

- The service is public but every `/chat` route requires the `X-API-Key` header, because `API_KEY` is set.
- Long agent runs hold a request open. For work that can exceed the request timeout, hand the run to Cloud Tasks or Pub/Sub and let the client poll or subscribe for the result.
- To use a Google-hosted model, set `LLM_MODEL` to a `google_vertexai:` model, add the `langchain-google-vertexai` package, and drop the Anthropic secret.
