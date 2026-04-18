#!/usr/bin/env python3
"""Print pipeline and vector-DB statistics.

Usage:
    python scripts/stats.py
    python scripts/stats.py --db ./db_docs --status data/status.json
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from storage.status import Status
from storage.vector_store import VectorStore
from rich.console import Console
from rich.table import Table

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Pipeline and vector-DB stats")
    parser.add_argument("--db", default=None,
                        help=f"ChromaDB path (default: {config.CHROMA_DB_PATH})")
    parser.add_argument("--status", default=None,
                        help=f"Status file path (default: {config.STATUS_FILE})")
    args = parser.parse_args()

    status_file = args.status or config.STATUS_FILE
    db_path = args.db or config.CHROMA_DB_PATH

    # Pipeline status
    st = Status(status_file)
    s = st.summary()
    by_type = st.by_source_type()

    table = Table(title=f"Pipeline — {status_file}", show_edge=False)
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")
    table.add_row("Total", str(s["total"]))
    table.add_row("Downloaded", str(s["downloaded"]))
    table.add_row("Transcribed", str(s["transcribed"]))
    table.add_row("Stored", str(s["stored"]))
    table.add_row("Failed (DLQ)", str(s["failed"]))
    table.add_row("Dead", str(s["dead"]))
    console.print(table)

    if by_type:
        t2 = Table(title="By source type", show_edge=False)
        t2.add_column("Type", style="bold cyan")
        t2.add_column("Count", justify="right")
        for k in sorted(by_type):
            t2.add_row(k, str(by_type[k]))
        console.print(t2)

    # Vector DB stats
    if os.path.exists(db_path):
        vs = VectorStore(db_path=db_path)
        vstats = vs.get_stats()
        t3 = Table(title=f"Vector DB — {db_path}", show_edge=False)
        t3.add_column("Metric", style="bold")
        t3.add_column("Value", justify="right")
        t3.add_row("Chunks", str(vstats["total_chunks"]))
        t3.add_row("Sources", str(vstats["total_sources"]))
        console.print(t3)
    else:
        console.print(f"[yellow]DB not found:[/yellow] {db_path}")


if __name__ == "__main__":
    main()
