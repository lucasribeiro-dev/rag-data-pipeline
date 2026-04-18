#!/usr/bin/env python3
"""MCP Server that exposes the ChromaDB knowledge base to Claude CLI."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
import config
from storage.vector_store import VectorStore

mcp = FastMCP("trade-knowledge-base")

_store = None


def _get_store():
    global _store
    if _store is None:
        _store = VectorStore(db_path=config.CHROMA_DB_PATH)
    return _store


@mcp.tool()
def search_knowledge_base(query: str, top_k: int = 5) -> str:
    """Search the crypto trading knowledge base (course + YouTube lives).

    Use this to find information about:
    - Trading strategies (repique, rompimento, top/bottom fishing, oversold bounce)
    - Technical analysis (chart patterns, indicators, support/resistance, Fibonacci)
    - Risk management (stop-loss, position sizing, leverage)
    - Market psychology and mindset
    - Futures trading, altcoin analysis
    - TradingView tools and setup

    Args:
        query: Search question in Portuguese or English
        top_k: Number of results to return (default: 5)
    """
    store = _get_store()
    results = store.query(query, top_k=top_k)

    if not results:
        return "Nenhum resultado encontrado na base de conhecimento."

    output = []
    for i, r in enumerate(results, 1):
        source = r["metadata"].get("source", "Unknown")
        module = r["metadata"].get("module", "")
        lesson = r["metadata"].get("lesson", "")
        doc_type = r["metadata"].get("type", "youtube")

        if module:
            header = f"[{i}] {module} / {lesson}"
        else:
            header = f"[{i}] {source}"

        output.append(f"{header}\n{r['text']}\n")

    return "\n---\n".join(output)


@mcp.tool()
def knowledge_base_stats() -> str:
    """Get statistics about the knowledge base."""
    store = _get_store()
    stats = store.get_stats()
    return (
        f"Total chunks: {stats['total_chunks']}\n"
        f"Total sources: {stats['total_sources']}\n"
        f"Sources:\n" + "\n".join(f"  - {s}" for s in stats["sources"])
    )


if __name__ == "__main__":
    mcp.run()
