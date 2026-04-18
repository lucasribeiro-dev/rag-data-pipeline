import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import yt_dlp
from rich.console import Console

console = Console()

MAX_WORKERS = 4


def _make_ydl_opts(output_dir):
    return {
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
        "ignoreerrors": True,
        "no_overwrites": True,
        "quiet": True,
        "no_warnings": True,
    }


def _extract_metadata(info):
    if info is None:
        return None
    title = info.get("title", "unknown")
    safe_title = yt_dlp.utils.sanitize_filename(title)
    return {
        "title": title,
        "date": info.get("upload_date", "unknown"),
        "url": info.get("webpage_url", info.get("original_url", "")),
        "safe_title": safe_title,
    }


def download_video(video_url, output_dir):
    """Download a single video as mp3. Returns metadata dict or None."""
    os.makedirs(output_dir, exist_ok=True)
    opts = _make_ydl_opts(output_dir)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(video_url, download=True)

    if info is None:
        return None

    meta = _extract_metadata(info)
    mp3_path = os.path.join(output_dir, f"{meta['safe_title']}.mp3")
    meta["file"] = mp3_path
    return meta


def _download_single(url, output_dir):
    """Download one video by URL. Used by thread pool."""
    try:
        return download_video(url, output_dir)
    except Exception as e:
        console.print(f"[red]Error downloading {url}: {e}[/red]")
        return None


def download_channel(channel_url, output_dir, limit=None, workers=MAX_WORKERS):
    """Download videos from a channel/playlist as mp3 using parallel threads."""
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: extract video URLs without downloading
    extract_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
    }
    if limit:
        extract_opts["playlistend"] = limit

    console.print("[dim]Extracting video list...[/dim]")
    with yt_dlp.YoutubeDL(extract_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    if info is None:
        console.print("[red]Failed to extract channel info.[/red]")
        return []

    # Collect all video URLs
    urls = []
    for entry in info.get("entries", []):
        if entry is None:
            continue
        url = entry.get("url") or entry.get("webpage_url", "")
        if url:
            urls.append(url)

    if not urls:
        console.print("[yellow]No videos found.[/yellow]")
        return []

    console.print(f"Found [bold]{len(urls)}[/bold] video(s), downloading with {workers} threads...")

    # Step 2: download in parallel
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_download_single, url, output_dir): url
            for url in urls
        }
        for future in as_completed(futures):
            meta = future.result()
            if meta:
                results.append(meta)
                console.print(f"  [green]Done:[/green] {meta['title']}")

    return results


def save_metadata(metadata_list, output_dir):
    """Save metadata list to a JSON file for later reference."""
    path = os.path.join(output_dir, "metadata.json")
    existing = []
    if os.path.exists(path):
        with open(path) as f:
            existing = json.load(f)

    # Merge by URL to avoid duplicates
    seen_urls = {m["url"] for m in existing}
    for m in metadata_list:
        if m["url"] not in seen_urls:
            existing.append(m)
            seen_urls.add(m["url"])

    with open(path, "w") as f:
        json.dump(existing, f, indent=2)
