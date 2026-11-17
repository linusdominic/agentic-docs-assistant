#!/usr/bin/env bash
# Deploy the API to Cloud Run, connected to a Cloud SQL for PostgreSQL instance.
#
# One-time setup this script expects (see deploy/README.md):
#   - a Cloud SQL PostgreSQL instance with a database for the app
#   - Secret Manager secrets: anthropic-api-key, docs-agent-database-url, docs-agent-api-key
#
# Usage:
#   PROJECT_ID=my-project REGION=europe-west1 SQL_INSTANCE=docs-agent-db ./deploy/cloudrun.sh
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID}"
: "${REGION:?Set REGION}"
: "${SQL_INSTANCE:?Set SQL_INSTANCE}"
SERVICE="${SERVICE:-agentic-docs-assistant}"
LLM_MODEL="${LLM_MODEL:-anthropic:claude-opus-5-5}"

gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --source . \
  --port 8080 \
  --memory 2Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 4 \
  --timeout 300 \
  --add-cloudsql-instances "$PROJECT_ID:$REGION:$SQL_INSTANCE" \
  --set-env-vars "LLM_MODEL=$LLM_MODEL" \
  --set-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest,DATABASE_URL=docs-agent-database-url:latest,API_KEY=docs-agent-api-key:latest" \
  --allow-unauthenticated

gcloud run services describe "$SERVICE" \
  --project "$PROJECT_ID" --region "$REGION" --format "value(status.url)"
