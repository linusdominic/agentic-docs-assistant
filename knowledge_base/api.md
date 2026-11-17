# Developer API

The Nimbus Notes API lets you read and write notes from your own scripts and integrations. It is available on Plus and Team plans.

## Authentication

Create a personal access token in Settings under Developer. Send it in the Authorization header as a bearer token. Tokens can be scoped to read-only or read-write and can be limited to a single notebook. A token is shown once when it is created, so store it somewhere safe. Revoke a token at any time from the same page.

## Rate limits

Each token can make 120 requests per minute on Plus and 600 requests per minute on Team. When you exceed the limit the API responds with status 429 and a Retry-After header that says how many seconds to wait. Bulk endpoints count as one request regardless of how many notes they touch.

## Core endpoints

`GET /v1/notes` lists notes, 50 per page, newest first. Filter with the `notebook_id`, `tag` and `updated_since` query parameters.

`GET /v1/notes/{id}` returns one note with its Markdown body.

`POST /v1/notes` creates a note. The body takes `title`, `content`, `notebook_id` and an optional list of `tags`.

`PATCH /v1/notes/{id}` updates a note. Send the `If-Match` header with the note's current version to avoid overwriting someone else's change; a mismatch returns status 412.

`DELETE /v1/notes/{id}` moves a note to Trash.

## Webhooks

Webhooks notify your server when notes change. Register a URL in Settings under Developer and choose the events you want: `note.created`, `note.updated` and `note.deleted`. Each delivery is signed with an HMAC-SHA256 signature in the `X-Nimbus-Signature` header. Deliveries that do not get a 2xx response within 10 seconds are retried up to five times with exponential backoff.

## Exporting your data

`POST /v1/exports` starts a full export of your account as a zip of Markdown files. The response includes an export id; poll `GET /v1/exports/{id}` until its status is `ready`, then download from the URL it returns. Download links expire after 24 hours.
