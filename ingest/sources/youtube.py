"""YouTube source — wraps the existing ingest/youtube.py downloader."""

from .base import Item, Source
from ingest.youtube import download_channel, download_video, save_metadata


class YouTubeSource(Source):
    name = "youtube"

    def detect(self, input_ref: str) -> bool:
        ref = input_ref.lower()
        return any(p in ref for p in ("youtube.com", "youtu.be"))

    def discover(self, input_ref: str, audio_dir: str = "data/audio",
                 kind: str = "video", limit: int = None, workers: int = 4, **_) -> list:
        if kind == "video" and "list=" not in input_ref and "/channel/" not in input_ref \
                and "/@" not in input_ref and "/playlist" not in input_ref:
            meta = download_video(input_ref, audio_dir)
            metas = [meta] if meta else []
        else:
            metas = download_channel(input_ref, audio_dir, limit=limit, workers=workers)

        if metas:
            save_metadata(metas, audio_dir)

        items = []
        for m in metas:
            items.append(Item(
                safe_key=f"youtube__{m['safe_title']}",
                source_type="youtube",
                original=m["url"],
                title=m["title"],
                staged_path=m["file"],
                needs_transcription=True,
                metadata={"url": m["url"], "date": m["date"]},
            ))
        return items
