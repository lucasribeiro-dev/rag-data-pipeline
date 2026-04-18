"""Base classes and registry for the pluggable Source abstraction.

A Source knows where input comes from and how to get a list of Items from it.
Each Item represents one piece of content (a YouTube video, a local mp3/mp4,
or a PDF file) that will flow through the same clean -> chunk -> store pipeline.
"""

import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import yt_dlp


@dataclass
class Item:
    safe_key: str
    source_type: str
    original: str
    title: str
    staged_path: Optional[str] = None
    needs_transcription: bool = False
    metadata: dict = field(default_factory=dict)


class Source:
    name: str = "base"

    def detect(self, input_ref: str) -> bool:
        raise NotImplementedError

    def discover(self, input_ref: str, **opts) -> list:
        raise NotImplementedError

    def fetch(self, item: Item, audio_dir: str) -> None:
        return None

    def extract_text(self, item: Item) -> str:
        raise NotImplementedError(f"{self.name} source does not support text extraction")


SOURCE_REGISTRY: list = []


def register(source: Source) -> None:
    SOURCE_REGISTRY.append(source)


def detect_source(input_ref: str) -> Source:
    for s in SOURCE_REGISTRY:
        if s.detect(input_ref):
            return s
    raise ValueError(f"No source handles: {input_ref}")


def get_source(name: str) -> Source:
    """Look up a source by name (for --type overrides)."""
    aliases = {"media": ("audio", "video"), "audio": ("audio",), "video": ("video",)}
    for s in SOURCE_REGISTRY:
        if s.name == name:
            return s
        if name in aliases and s.name in ("media",):
            return s
    raise ValueError(f"Unknown source type: {name}")


def slug(text: str) -> str:
    """Build a filesystem- and ChromaDB-safe slug from arbitrary text."""
    s = yt_dlp.utils.sanitize_filename(text)
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s.strip("_") or "item"


def slug_of_relpath(abs_path: str, root: str) -> str:
    """Turn an absolute file path into a flat slug relative to root.

    Directory separators become `_`; the extension is dropped.
    """
    rel = os.path.relpath(abs_path, root)
    stem, _ = os.path.splitext(rel)
    parts = re.split(r"[\\/]+", stem)
    return slug("_".join(p for p in parts if p))


def short_hash(text: str, n: int = 6) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]
