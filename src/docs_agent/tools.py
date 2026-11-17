"""The tools the agent can call: one that reads (retrieval) and one that acts (tickets)."""

from typing import Protocol

from langchain_core.tools import BaseTool, tool
from langgraph.types import interrupt

from docs_agent.db import Chunk


class Retriever(Protocol):
    async def search(self, query: str, k: int = 4) -> list[Chunk]: ...


class Tickets(Protocol):
    async def create(self, title: str, description: str) -> int: ...


def make_tools(retriever: Retriever, tickets: Tickets, k: int = 4) -> list[BaseTool]:
    """Build the agent's tools around the given stores, so tests can pass in fakes."""

    @tool
    async def search_docs(query: str) -> str:
        """Search the product documentation and return the most relevant passages.

        Use this before answering any question about the product. Each passage is
        labelled with the file it came from, so the answer can cite its sources.
        """
        chunks = await retriever.search(query, k=k)
        if not chunks:
            return "No relevant passages found."
        return "\n\n---\n\n".join(f"[source: {c.source}]\n{c.content}" for c in chunks)

    @tool
    async def create_ticket(title: str, description: str) -> str:
        """File a support ticket for a human agent to follow up on.

        Use this when the documentation does not resolve the problem, or when the user
        asks to contact support. The user is asked to approve the ticket before it is filed.
        """
        # Pause the graph here. The run resumes when the API receives the user's decision.
        decision = interrupt(
            {"action": "create_ticket", "title": title, "description": description}
        )
        if not (isinstance(decision, dict) and decision.get("approved")):
            return "The user declined, so no ticket was created."
        ticket_id = await tickets.create(title, description)
        return f"Created ticket #{ticket_id}."

    return [search_docs, create_ticket]
