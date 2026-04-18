#!/usr/bin/env python3
"""Download audio from YouTube.

Usage:
    python scripts/download.py --channel URL
    python scripts/download.py --video URL
    python scripts/download.py --playlist URL
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from ingest.youtube import download_channel, download_video, save_metadata
from storage.status import Status
from rich.console import Console
from rich.panel import Panel

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Download YouTube audio")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--channel", help="YouTube channel URL")
    group.add_argument("--video", help="Single YouTube video URL")
    group.add_argument("--playlist", help="YouTube playlist URL")
    parser.add_argument("--limit", type=int, default=None, help="Max number of videos to download")
    parser.add_argument("--workers", type=int, default=4, help="Parallel download threads (default: 4)")
    parser.add_argument("--output", default=None, help=f"Audio output directory (default: {config.AUDIO_DIR}, env: AUDIO_DIR)")
    parser.add_argument("--status", default=None, help=f"Status file path (default: {config.STATUS_FILE}, env: STATUS_FILE)")
    args = parser.parse_args()

    audio_dir = args.output or config.AUDIO_DIR
    status_file = args.status or config.STATUS_FILE

    os.makedirs(audio_dir, exist_ok=True)
    status = Status(status_file)

    console.print(Panel("[bold]Download YouTube Audio[/bold]", border_style="blue"))

    if args.video:
        meta = download_video(args.video, audio_dir)
        metadata_list = [meta] if meta else []
    else:
        url = args.channel or args.playlist
        metadata_list = download_channel(url, audio_dir, limit=args.limit, workers=args.workers)

    if not metadata_list:
        console.print("[red]No videos downloaded.[/red]")
        return

    save_metadata(metadata_list, audio_dir)

    new_count = 0
    skipped = 0
    for m in metadata_list:
        key = m["safe_title"]
        if status.is_downloaded(key):
            skipped += 1
            continue
        status.mark_downloaded(key, title=m["title"], url=m["url"], date=m["date"],
                               source_type="youtube")
        new_count += 1

    console.print(f"[green]Downloaded {new_count} new video(s), {skipped} already tracked[/green]")


if __name__ == "__main__":
    main()
