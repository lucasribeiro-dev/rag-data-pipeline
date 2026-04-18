"""PDF source — extracts text via pypdf; skips Whisper."""

import os
from .base import Item, Source, short_hash, slug_of_relpath


def _walk_pdfs(root: str):
    if os.path.isfile(root):
        if root.lower().endswith(".pdf"):
            yield root
        return
    root = os.path.abspath(root)
    for dirpath, _, filenames in os.walk(root):
        for f in sorted(filenames):
            if f.lower().endswith(".pdf"):
                yield os.path.join(dirpath, f)


class PDFSource(Source):
    name = "pdf"

    def detect(self, input_ref: str) -> bool:
        if not os.path.exists(input_ref):
            return False
        if os.path.isfile(input_ref):
            return input_ref.lower().endswith(".pdf")
        for _ in _walk_pdfs(input_ref):
            return True
        return False

    def discover(self, input_ref: str, **_) -> list:
        import pypdf

        abs_ref = os.path.abspath(input_ref)
        root = abs_ref if os.path.isdir(abs_ref) else os.path.dirname(abs_ref)

        items = []
        seen_keys = set()
        for path in _walk_pdfs(abs_ref):
            base_slug = slug_of_relpath(path, root) or os.path.basename(path)
            key = f"pdf__{base_slug}"
            if key in seen_keys:
                key = f"pdf__{base_slug}_{short_hash(path)}"
            seen_keys.add(key)

            page_count = 0
            try:
                page_count = len(pypdf.PdfReader(path).pages)
            except Exception:
                pass

            items.append(Item(
                safe_key=key,
                source_type="pdf",
                original=path,
                title=os.path.splitext(os.path.basename(path))[0],
                staged_path=None,
                needs_transcription=False,
                metadata={"source_path": path, "page_count": page_count},
            ))
        return items

    def extract_text(self, item: Item) -> str:
        import pypdf

        reader = pypdf.PdfReader(item.original)
        pages = []
        empty = 0
        total = len(reader.pages)
        for page in reader.pages:
            try:
                txt = page.extract_text() or ""
            except Exception:
                txt = ""
            if txt.strip():
                pages.append(txt)
            else:
                empty += 1

        if total and empty / total > 0.5:
            raise RuntimeError("no text layer — needs OCR")

        return "\n\n".join(pages)
