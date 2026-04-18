"""Local audio/video files source — feeds Whisper transcription."""

import os
from .base import Item, Source, short_hash, slug_of_relpath

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov"}
MEDIA_EXTS = AUDIO_EXTS | VIDEO_EXTS


def _kind_for(ext: str) -> str:
    return "audio" if ext.lower() in AUDIO_EXTS else "video"


def _walk(root: str, max_depth):
    if os.path.isfile(root):
        yield root
        return
    root = os.path.abspath(root)
    for dirpath, _, filenames in os.walk(root):
        if max_depth is not None:
            depth = dirpath[len(root):].count(os.sep)
            if depth > max_depth:
                continue
        for f in sorted(filenames):
            yield os.path.join(dirpath, f)


class MediaFileSource(Source):
    name = "media"

    def detect(self, input_ref: str) -> bool:
        if not os.path.exists(input_ref):
            return False
        if os.path.isfile(input_ref):
            return os.path.splitext(input_ref)[1].lower() in MEDIA_EXTS
        # Directory: claim if any media file is present within max_depth of 8
        for f in _walk(input_ref, max_depth=8):
            if os.path.splitext(f)[1].lower() in MEDIA_EXTS:
                return True
        return False

    def discover(self, input_ref: str, max_depth=None, **_) -> list:
        abs_ref = os.path.abspath(input_ref)
        root = abs_ref if os.path.isdir(abs_ref) else os.path.dirname(abs_ref)

        items = []
        seen_keys = set()
        for path in _walk(abs_ref, max_depth):
            ext = os.path.splitext(path)[1].lower()
            if ext not in MEDIA_EXTS:
                continue
            kind = _kind_for(ext)
            base_slug = slug_of_relpath(path, root) or os.path.basename(path)
            key = f"{kind}__{base_slug}"
            if key in seen_keys:
                key = f"{kind}__{base_slug}_{short_hash(path)}"
            seen_keys.add(key)

            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0

            items.append(Item(
                safe_key=key,
                source_type=kind,
                original=path,
                title=os.path.splitext(os.path.basename(path))[0],
                staged_path=path,
                needs_transcription=True,
                metadata={"source_path": path, "ext": ext, "size_bytes": size},
            ))
        return items
