"""ASGI entry point: ``uvicorn docs_agent.main:app``."""

import os

from docs_agent.api import create_app

app = create_app()


def serve() -> None:
    import uvicorn

    uvicorn.run("docs_agent.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
