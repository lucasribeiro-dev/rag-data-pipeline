#!/usr/bin/env python3
"""Interactive chat CLI for querying the knowledge base.

Usage:
    python scripts/chat.py
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from storage.vector_store import VectorStore
from bot.rag import RAGBot
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Interactive RAG chat REPL")
    parser.add_argument("--db", default=None,
                        help=f"ChromaDB path (default: {config.CHROMA_DB_PATH}, env: CHROMA_DB_PATH)")
    args = parser.parse_args()

    db_path = args.db or config.CHROMA_DB_PATH
    store = VectorStore(db_path=db_path)
    bot = RAGBot(store)

    stats = store.get_stats()
    console.print(
        Panel(
            f"[bold]Knowledge Base Chat[/bold]\n\n"
            f"DB: [magenta]{db_path}[/magenta]\n"
            f"Sources: {stats['total_sources']} | Chunks: {stats['total_chunks']}\n\n"
            f"Commands: [dim]/quit[/dim]  [dim]/stats[/dim]  [dim]/clear[/dim]",
            border_style="blue",
        )
    )

    if stats["total_chunks"] == 0:
        console.print(
            "[yellow]Warning: The knowledge base is empty. "
            "Run `make ingest INPUT=...` first to add content.[/yellow]\n"
        )

    chat_history = []

    while True:
        try:
            question = console.input("\n[bold green]You:[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not question:
            continue

        if question == "/quit":
            console.print("[dim]Goodbye![/dim]")
            break

        if question == "/stats":
            stats = store.get_stats()
            console.print(
                Panel(
                    f"Total chunks: {stats['total_chunks']}\n"
                    f"Total sources: {stats['total_sources']}\n"
                    f"Sources:\n" + "\n".join(f"  - {s}" for s in stats["sources"]),
                    title="Knowledge Base Stats",
                    border_style="cyan",
                )
            )
            continue

        if question == "/clear":
            chat_history = []
            console.print("[dim]Chat history cleared.[/dim]")
            continue

        with console.status("[bold cyan]Thinking...[/bold cyan]"):
            result = bot.ask(question, chat_history)

        # Display answer
        console.print(f"\n[bold blue]Bot:[/bold blue]")
        console.print(Markdown(result["answer"]))

        if result["sources"]:
            sources_str = ", ".join(result["sources"])
            console.print(f"\n[dim]Sources: {sources_str}[/dim]")

        # Update chat history
        chat_history.append({"role": "user", "content": question})
        chat_history.append({"role": "assistant", "content": result["answer"]})

        # Keep history manageable (last 10 turns)
        if len(chat_history) > 20:
            chat_history = chat_history[-20:]


if __name__ == "__main__":
    main()
