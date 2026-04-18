import json
import os

MAX_RETRIES = 3


class Status:
    """Track pipeline status for each video in a JSON file.

    Each entry is keyed by safe_title:
    {
        "safe_title": {
            "title": "Original Title",
            "url": "https://...",
            "date": "20240101",
            "downloaded": true,
            "transcribed": false,
            "stored": false,
            "failed": false,
            "fail_reason": "",
            "fail_count": 0
        }
    }
    """

    def __init__(self, path):
        self._path = path
        self._data = {}
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            with open(self._path) as f:
                self._data = json.load(f)

    def _save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=2)

    def mark_downloaded(self, safe_title, title="", url="", date="",
                        source_type="", source_path=""):
        entry = self._data.get(safe_title, {})
        entry.update({
            "title": title or entry.get("title", safe_title),
            "url": url or entry.get("url", ""),
            "date": date or entry.get("date", ""),
            "source_type": source_type or entry.get("source_type", ""),
            "source_path": source_path or entry.get("source_path", ""),
            "downloaded": True,
            "transcribed": entry.get("transcribed", False),
            "stored": entry.get("stored", False),
            "failed": entry.get("failed", False),
            "fail_reason": entry.get("fail_reason", ""),
            "fail_count": entry.get("fail_count", 0),
        })
        self._data[safe_title] = entry
        self._save()

    def mark_transcribed(self, safe_title):
        if safe_title in self._data:
            self._data[safe_title]["transcribed"] = True
            self._data[safe_title]["failed"] = False
            self._data[safe_title]["fail_reason"] = ""
            self._save()

    def mark_stored(self, safe_title):
        if safe_title in self._data:
            self._data[safe_title]["stored"] = True
            self._save()

    def mark_failed(self, safe_title, reason=""):
        """Move item to DLQ. Increments fail_count."""
        if safe_title in self._data:
            entry = self._data[safe_title]
            entry["failed"] = True
            entry["fail_reason"] = reason
            entry["fail_count"] = entry.get("fail_count", 0) + 1
            self._save()

    def is_downloaded(self, safe_title):
        return self._data.get(safe_title, {}).get("downloaded", False)

    def is_transcribed(self, safe_title):
        return self._data.get(safe_title, {}).get("transcribed", False)

    def is_stored(self, safe_title):
        return self._data.get(safe_title, {}).get("stored", False)

    def is_failed(self, safe_title):
        return self._data.get(safe_title, {}).get("failed", False)

    def pending_transcription(self):
        """Return safe_titles that are downloaded but not transcribed and not in DLQ."""
        return [k for k, v in self._data.items()
                if v.get("downloaded") and not v.get("transcribed") and not v.get("failed")]

    def pending_retry(self):
        """Return safe_titles in DLQ that haven't exceeded max retries."""
        return [k for k, v in self._data.items()
                if v.get("failed") and v.get("fail_count", 0) < MAX_RETRIES]

    def dead(self):
        """Return safe_titles that exceeded max retries."""
        return [k for k, v in self._data.items()
                if v.get("failed") and v.get("fail_count", 0) >= MAX_RETRIES]

    def pending_store(self):
        """Return safe_titles that are transcribed but not stored."""
        return [k for k, v in self._data.items()
                if v.get("transcribed") and not v.get("stored")]

    def get(self, safe_title):
        return self._data.get(safe_title) or self._data.get(f"youtube__{safe_title}")

    def all(self):
        return dict(self._data)

    def by_source_type(self):
        """Return count of entries grouped by source_type (empty string for legacy)."""
        counts = {}
        for v in self._data.values():
            st = v.get("source_type") or "youtube"
            counts[st] = counts.get(st, 0) + 1
        return counts

    def summary(self):
        total = len(self._data)
        downloaded = sum(1 for v in self._data.values() if v.get("downloaded"))
        transcribed = sum(1 for v in self._data.values() if v.get("transcribed"))
        stored = sum(1 for v in self._data.values() if v.get("stored"))
        failed = sum(1 for v in self._data.values() if v.get("failed"))
        dead = sum(1 for v in self._data.values()
                   if v.get("failed") and v.get("fail_count", 0) >= MAX_RETRIES)
        return {
            "total": total,
            "downloaded": downloaded,
            "transcribed": transcribed,
            "stored": stored,
            "failed": failed,
            "dead": dead,
        }
