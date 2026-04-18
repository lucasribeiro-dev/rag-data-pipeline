#!/usr/bin/env python3
"""Transcribe audio files using auto-scaling multiprocessing workers.

Usage:
    python scripts/transcribe.py                    # auto-detect workers
    python scripts/transcribe.py --max-workers 4    # cap at 4 workers
    python scripts/transcribe.py --retry            # retry DLQ items
"""

import argparse
import sys
import os
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from ingest.transcribe import transcribe_auto
from ingest.resources import get_resources, estimate_max_workers, WHISPER_MODEL_MEMORY
from storage.status import Status
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.live import Live

console = Console()


def _print_resources(model_name):
    """Print current system resources and estimated capacity."""
    res = get_resources()
    max_w, _ = estimate_max_workers(model_name)
    model_mem = WHISPER_MODEL_MEMORY.get(model_name, 2.0)

    table = Table(title="System Resources", show_edge=False)
    table.add_column("Resource", style="bold")
    table.add_column("Value")
    table.add_column("Status")

    cpu_color = "green" if res["cpu_percent"] < 60 else "yellow" if res["cpu_percent"] < 85 else "red"
    table.add_row("CPU", f"{res['cpu_percent']:.0f}% ({res['cpu_count']} cores)", f"[{cpu_color}]{cpu_color}[/{cpu_color}]")

    ram_color = "green" if res["ram_available_gb"] > model_mem * 2 else "yellow" if res["ram_available_gb"] > model_mem else "red"
    table.add_row("RAM", f"{res['ram_available_gb']:.1f}GB free / {res['ram_total_gb']:.1f}GB", f"[{ram_color}]{ram_color}[/{ram_color}]")

    if res["gpu"]:
        for gpu in res["gpu"]:
            gpu_color = "green" if gpu["free_gb"] > model_mem * 2 else "yellow" if gpu["free_gb"] > model_mem else "red"
            table.add_row("GPU", f"{gpu['name']}: {gpu['free_gb']:.1f}GB free / {gpu['total_gb']:.1f}GB", f"[{gpu_color}]{gpu_color}[/{gpu_color}]")
    else:
        table.add_row("GPU", "not available (CPU mode)", "[dim]--[/dim]")

    table.add_row("Model", f"{model_name} (~{model_mem}GB per worker)", "")
    table.add_row("Max workers", str(max_w), "")

    console.print(table)


def _format_elapsed(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def _build_progress_table(workers_state, completed, total, log_lines):
    """Build a live-updating table showing worker status + log."""
    table = Table(show_edge=False, show_header=True, expand=True)
    table.add_column("Worker", style="bold cyan", width=12)
    table.add_column("Device", width=6)
    table.add_column("Status", ratio=1)
    table.add_column("Elapsed", width=10, justify="right")

    for wid in sorted(workers_state, key=str):
        ws = workers_state[wid]
        label = str(wid)
        device = ws.get("device", "?")
        device_color = "green" if device == "cuda" else "yellow"
        dev_str = f"[{device_color}]{device}[/{device_color}]"

        if ws.get("file") and ws.get("start_time"):
            elapsed = _format_elapsed(time.time() - ws["start_time"])
            table.add_row(label, dev_str, f"[bold]{ws['file']}[/bold]", elapsed)
        elif ws.get("ready"):
            table.add_row(label, dev_str, "[dim]waiting for next file...[/dim]", "")
        else:
            spawn = ws.get("spawn_time")
            loading_time = _format_elapsed(time.time() - spawn) if spawn else ""
            table.add_row(label, "", f"[dim]loading model...[/dim]", loading_time)

    table.add_row("", "", "", "")
    table.add_row("[bold]Progress[/bold]", "", f"{completed}/{total} files", "")

    # Show last N log lines
    for line in log_lines[-8:]:
        table.add_row("", "", line, "")

    return table


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio files with auto-scaling")
    parser.add_argument("--model", default=config.WHISPER_MODEL, help=f"Whisper model (default: {config.WHISPER_MODEL})")
    parser.add_argument("--max-workers", type=int, default=None, help="Max worker processes (default: auto-detect)")
    parser.add_argument("--retry", action="store_true", help="Retry failed transcriptions from DLQ")
    parser.add_argument("--input", default=None, help=f"Audio input directory (default: {config.AUDIO_DIR}, env: AUDIO_DIR)")
    parser.add_argument("--output", default=None, help=f"Transcriptions output directory (default: {config.TRANSCRIPTIONS_DIR}, env: TRANSCRIPTIONS_DIR)")
    parser.add_argument("--status", default=None, help=f"Status file path (default: {config.STATUS_FILE}, env: STATUS_FILE)")
    args = parser.parse_args()

    audio_dir = args.input or config.AUDIO_DIR
    transcriptions_dir = args.output or config.TRANSCRIPTIONS_DIR
    status_file = args.status or config.STATUS_FILE

    os.makedirs(transcriptions_dir, exist_ok=True)
    status = Status(status_file)

    console.print(Panel("[bold]Transcribe Audio[/bold]", border_style="blue"))
    _print_resources(args.model)

    if args.retry:
        pending = status.pending_retry()
        if not pending:
            console.print("[yellow]No failed transcriptions to retry.[/yellow]")
            dead = status.dead()
            if dead:
                console.print(f"[red]{len(dead)} item(s) exceeded max retries (dead).[/red]")
            return
        console.print(f"\nRetrying [bold]{len(pending)}[/bold] failed transcription(s)...")
    else:
        pending = status.pending_transcription()
        # PDFs are extracted, not transcribed — skip them here
        pending = [k for k in pending
                   if (status.get(k) or {}).get("source_type") != "pdf"]
        if not pending:
            console.print("[yellow]No new audio to transcribe.[/yellow]")
            failed = status.pending_retry()
            if failed:
                console.print(f"[dim]{len(failed)} item(s) in DLQ. Use --retry to reprocess.[/dim]")
            return

    # Build file list
    files = []
    for safe_title in pending:
        entry = status.get(safe_title) or {}
        audio_path = entry.get("source_path") or os.path.join(audio_dir, f"{safe_title}.mp3")
        if not os.path.exists(audio_path):
            console.print(f"  [red]Missing audio: {safe_title}[/red]")
            status.mark_failed(safe_title, reason="audio file not found")
            continue
        files.append((safe_title, audio_path))

    if not files:
        console.print("[yellow]No audio files to process.[/yellow]")
        return

    console.print(f"\n[bold]{len(files)}[/bold] file(s) to transcribe\n")

    # Shared state for live display
    workers_state = {}
    log_lines = []
    completed_count = [0]
    total = len(files)
    lock = threading.Lock()

    def on_event(event_type, name, data):
        with lock:
            if event_type == "ready":
                workers_state[name] = {
                    "device": data, "ready": True,
                    "file": None, "start_time": None,
                    "spawn_time": time.time(),
                }
                log_lines.append(f"[cyan]{name}[/cyan] ready ([{'green' if data == 'cuda' else 'yellow'}]{data}[/])")

            elif event_type == "working":
                wid = f"worker-{name}"
                if wid not in workers_state:
                    workers_state[wid] = {
                        "device": "?", "ready": True,
                        "file": None, "start_time": None,
                        "spawn_time": time.time(),
                    }
                workers_state[wid]["file"] = data
                workers_state[wid]["start_time"] = time.time()

            elif event_type == "ok":
                completed_count[0] += 1
                for ws in workers_state.values():
                    if ws.get("file") == name:
                        ws["file"] = None
                        ws["start_time"] = None
                log_lines.append(f"[green]Done [{data}]:[/green] {name}")

            elif event_type == "error":
                completed_count[0] += 1
                for ws in workers_state.values():
                    if ws.get("file") == name:
                        ws["file"] = None
                        ws["start_time"] = None
                log_lines.append(f"[red]Failed:[/red] {name}")

            elif event_type == "scale":
                log_lines.append(f"[yellow]Scaled up:[/yellow] {name}")

    # Run transcription with live display
    result_holder = [None, None]

    def run_transcribe():
        s, f = transcribe_auto(
            files, transcriptions_dir, args.model, status_file, args.max_workers, on_event
        )
        result_holder[0] = s
        result_holder[1] = f

    worker_thread = threading.Thread(target=run_transcribe)
    worker_thread.start()

    with Live(console=console, refresh_per_second=1) as live:
        while worker_thread.is_alive():
            with lock:
                table = _build_progress_table(workers_state, completed_count[0], total, log_lines)
            live.update(table)
            time.sleep(1)
        # Final update
        with lock:
            table = _build_progress_table(workers_state, completed_count[0], total, log_lines)
        live.update(table)

    worker_thread.join()
    successes = result_holder[0] or []
    failures = result_holder[1] or []

    # Results
    console.print()
    table = Table(title="Results")
    table.add_column("Status", style="bold")
    table.add_column("Count")
    table.add_row("[green]Transcribed[/green]", str(len(successes)))
    table.add_row("[red]Failed (DLQ)[/red]", str(len(failures)))
    console.print(table)

    if failures:
        console.print("\n[red]Failed items:[/red]")
        for safe_title, reason in failures:
            entry = status.get(safe_title)
            count = entry.get("fail_count", 0) if entry else 0
            console.print(f"  [{count}/3] {safe_title}: {reason}")
        console.print("[dim]Use --retry to reprocess failed items.[/dim]")

    if successes:
        console.print(f"\n[green]Done! {len(successes)} file(s) transcribed.[/green]")


if __name__ == "__main__":
    main()
