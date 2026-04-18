#!/usr/bin/env python3
"""Unified ingest orchestrator: YouTube URLs OR local mp3/mp4/pdf.

Detects input kind, runs the matching Source, then drives the shared
transcribe (Whisper) / extract (pypdf) / clean / chunk / store pipeline.

Usage:
    python scripts/ingest.py --input https://youtube.com/watch?v=...
    python scripts/ingest.py --input /path/to/media_or_pdf
    python scripts/ingest.py --input ./docs --type pdf --db ./db_docs
"""

import argparse
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from ingest.cleaner import clean
from ingest.sources import detect_source, get_source
from ingest.transcribe import transcribe_auto
from storage.status import Status
from rich.console import Console
from rich.panel import Panel

console = Console()

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable


def _resolve_source(input_ref, forced_type):
    if forced_type and forced_type != "auto":
        return get_source(forced_type)
    return detect_source(input_ref)


def _youtube_kind(input_ref):
    ref = input_ref.lower()
    if "list=" in ref or "/playlist" in ref:
        return "playlist"
    if "/channel/" in ref or "/@" in ref or "/c/" in ref or "/user/" in ref:
        return "channel"
    return "video"


def _run_store(status_file, transcriptions_dir, db_path):
    cmd = [PYTHON, os.path.join(SCRIPTS_DIR, "store.py"),
           "--status", status_file,
           "--input", transcriptions_dir,
           "--db", db_path]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description="Unified ingest: YouTube or local mp3/mp4/pdf")
    parser.add_argument("--input", required=True, help="URL (YouTube) or path to file/directory")
    parser.add_argument("--type", default="auto",
                        choices=["auto", "youtube", "media", "audio", "video", "pdf"],
                        help="Force source type (default: auto-detect)")
    parser.add_argument("--db", default=None,
                        help=f"ChromaDB path (default: {config.CHROMA_DB_PATH}, env: CHROMA_DB_PATH)")
    parser.add_argument("--status", default=None,
                        help=f"Status file (default: {config.STATUS_FILE}, env: STATUS_FILE)")
    parser.add_argument("--audio-dir", default=None,
                        help=f"Audio dir for YouTube downloads (default: {config.AUDIO_DIR})")
    parser.add_argument("--transcriptions-dir", default=None,
                        help=f"Transcriptions dir (default: {config.TRANSCRIPTIONS_DIR})")
    parser.add_argument("--model", default=config.WHISPER_MODEL,
                        help=f"Whisper model (default: {config.WHISPER_MODEL})")
    parser.add_argument("--workers", type=int, default=4, help="Download workers (YouTube)")
    parser.add_argument("--max-workers", type=int, default=None, help="Max transcription workers")
    parser.add_argument("--limit", type=int, default=None, help="Max videos (YouTube channel/playlist)")
    parser.add_argument("--max-depth", type=int, default=None, help="Max recursion depth (local dirs)")
    args = parser.parse_args()

    status_file = args.status or config.STATUS_FILE
    audio_dir = args.audio_dir or config.AUDIO_DIR
    transcriptions_dir = args.transcriptions_dir or config.TRANSCRIPTIONS_DIR
    db_path = args.db or config.CHROMA_DB_PATH

    os.makedirs(os.path.dirname(status_file) or ".", exist_ok=True)
    os.makedirs(audio_dir, exist_ok=True)
    os.makedirs(transcriptions_dir, exist_ok=True)

    status = Status(status_file)
    source = _resolve_source(args.input, args.type)

    console.print(Panel(
        f"[bold]Ingest[/bold] — source=[cyan]{source.name}[/cyan]  db=[magenta]{db_path}[/magenta]",
        border_style="blue",
    ))

    discover_kwargs = {
        "audio_dir": audio_dir,
        "limit": args.limit,
        "workers": args.workers,
        "max_depth": args.max_depth,
    }
    if source.name == "youtube":
        discover_kwargs["kind"] = _youtube_kind(args.input)

    items = source.discover(args.input, **discover_kwargs)
    if not items:
        console.print("[yellow]No items discovered.[/yellow]")
        return

    console.print(f"Discovered [bold]{len(items)}[/bold] item(s).")

    # Register all items in status
    for it in items:
        status.mark_downloaded(
            it.safe_key,
            title=it.title,
            url=it.metadata.get("url", ""),
            date=it.metadata.get("date", ""),
            source_type=it.source_type,
            source_path=it.metadata.get("source_path", ""),
        )

    # Partition
    media_items = [it for it in items
                   if it.needs_transcription and not status.is_transcribed(it.safe_key)]
    pdf_items = [it for it in items
                 if it.source_type == "pdf" and not status.is_transcribed(it.safe_key)]

    if media_items:
        files = [(it.safe_key, it.staged_path) for it in media_items]
        console.print(f"\n[bold blue]Transcribing[/bold blue] {len(files)} media file(s) with Whisper ({args.model})...")

        def _on_event(kind, name, data):
            if kind == "ok":
                console.print(f"  [green]transcribed:[/green] {name}")
            elif kind == "error":
                console.print(f"  [red]failed:[/red] {name}: {data}")

        transcribe_auto(files, transcriptions_dir, args.model, status_file,
                        args.max_workers, _on_event)

    if pdf_items:
        console.print(f"\n[bold blue]Extracting[/bold blue] {len(pdf_items)} PDF(s)...")
        # Refresh status to pick up anything transcribe just wrote
        status = Status(status_file)
        for it in pdf_items:
            try:
                text = source.extract_text(it) if source.name == "pdf" else get_source("pdf").extract_text(it)
                cleaned = clean(text, "pdf")
                out_path = os.path.join(transcriptions_dir, f"{it.safe_key}.txt")
                with open(out_path, "w") as f:
                    f.write(cleaned)
                status.mark_transcribed(it.safe_key)
                console.print(f"  [green]extracted:[/green] {it.safe_key} ({it.metadata.get('page_count', '?')} pages)")
            except Exception as e:
                status.mark_failed(it.safe_key, reason=str(e))
                console.print(f"  [red]failed:[/red] {it.safe_key}: {e}")

    # Store phase — shell to store.py for consistency with legacy --db flow
    console.print("\n[bold blue]Storing[/bold blue] pending transcriptions...")
    _run_store(status_file, transcriptions_dir, db_path)

    console.print(Panel("[bold green]Done.[/bold green]", border_style="green"))


if __name__ == "__main__":
    main()
