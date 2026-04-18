#!/usr/bin/env python3
"""Clean, chunk, and store transcriptions that haven't been stored yet.

Uses threads to clean+chunk files in parallel, then stores in ChromaDB.

Usage:
    python scripts/store.py
    python scripts/store.py --workers 4
"""

import argparse
import sys
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from ingest.cleaner import clean_text
from processing.chunker import chunk_text
from storage.vector_store import VectorStore
from storage.status import Status
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

console = Console()


def _process_file(safe_title, status, transcriptions_dir):
    """Read, clean, and chunk a single transcription. Returns (safe_title, chunks, url) or None."""
    filepath = os.path.join(transcriptions_dir, f"{safe_title}.txt")
    if not os.path.exists(filepath):
        return None

    with open(filepath) as f:
        raw_text = f.read()

    cleaned = clean_text(raw_text)
    chunks = chunk_text(cleaned, config.CHUNK_SIZE, config.CHUNK_OVERLAP)

    entry = status.get(safe_title)
    source_url = entry.get("url", "") if entry else ""

    return safe_title, chunks, source_url


def main():
    parser = argparse.ArgumentParser(description="Store transcriptions in vector DB")
    parser.add_argument("--workers", type=int, default=4, help="Thread workers for clean+chunk (default: 4)")
    parser.add_argument("--input", default=None, help=f"Transcriptions directory (default: {config.TRANSCRIPTIONS_DIR}, env: TRANSCRIPTIONS_DIR)")
    parser.add_argument("--status", default=None, help=f"Status file path (default: {config.STATUS_FILE}, env: STATUS_FILE)")
    parser.add_argument("--db", default=None, help=f"ChromaDB path (default: {config.CHROMA_DB_PATH}, env: CHROMA_DB_PATH)")
    args = parser.parse_args()

    transcriptions_dir = args.input or config.TRANSCRIPTIONS_DIR
    status_file = args.status or config.STATUS_FILE
    db_path = args.db or config.CHROMA_DB_PATH

    console.print(Panel("[bold]Store in Vector DB[/bold]", border_style="blue"))

    status = Status(status_file)
    pending = status.pending_store()

    if not pending:
        console.print("[yellow]No new transcriptions to store.[/yellow]")
        return

    console.print(f"[bold]{len(pending)}[/bold] file(s) to process with {args.workers} threads\n")

    # Phase 1: Clean + Chunk in parallel threads
    console.print("[bold blue]Phase 1/2:[/bold blue] Cleaning and chunking...")
    prepared = []
    missing = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_process_file, title, status, transcriptions_dir): title
            for title in pending
        }
        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
            BarColumn(), MofNCompleteColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Chunking...", total=len(futures))
            for future in as_completed(futures):
                result = future.result()
                if result:
                    prepared.append(result)
                else:
                    missing.append(futures[future])
                progress.advance(task)

    if missing:
        for title in missing:
            console.print(f"  [red]Missing transcription: {title}[/red]")

    if not prepared:
        console.print("[yellow]No files to store.[/yellow]")
        return

    total_chunks_prepared = sum(len(chunks) for _, chunks, _ in prepared)
    console.print(f"  Prepared {total_chunks_prepared} chunks from {len(prepared)} file(s)\n")

    # Phase 2: Store in ChromaDB (sequential - embedding model handles batching)
    console.print("[bold blue]Phase 2/2:[/bold blue] Embedding and storing...")
    store = VectorStore(db_path=db_path)
    total_added = 0

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Storing...", total=len(prepared))
        for safe_title, chunks, source_url in prepared:
            entry = status.get(safe_title) or {}
            metadatas = [
                {
                    "source": safe_title,
                    "url": entry.get("url", source_url),
                    "source_type": entry.get("source_type", "") or "youtube",
                    "source_path": entry.get("source_path", ""),
                    "chunk_index": str(i),
                }
                for i in range(len(chunks))
            ]

            added = store.add_documents(chunks, metadatas)
            total_added += added
            status.mark_stored(safe_title)
            progress.console.print(
                f"  [green]{safe_title}[/green]: {len(chunks)} chunks ({added} new)"
            )
            progress.advance(task)

    stats = store.get_stats()
    console.print(
        Panel(
            f"[bold]Done![/bold]\n\n"
            f"New chunks added: {total_added}\n"
            f"Total chunks in DB: {stats['total_chunks']}\n"
            f"Total sources: {stats['total_sources']}",
            title="Results",
            border_style="green",
        )
    )


if __name__ == "__main__":
    main()
