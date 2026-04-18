import re


# Portuguese filler patterns (careful not to hit real words)
_FILLERS_PT = re.compile(
    r"\b(é:::?|éh+|ahh+|ehh+|humm+|hmm+|ãh+|né né|tá tá)\b",
    re.IGNORECASE,
)

# Repeated consecutive words 3+ times: "o o o" -> "o" (2x could be emphasis)
_REPEATED_WORDS = re.compile(r"\b(\w+)(\s+\1){2,}\b", re.IGNORECASE)

# Excessive punctuation: "!!!" -> "!", "???" -> "?"
_EXCESS_PUNCT = re.compile(r"([!?])\1{2,}")


def clean_text(text):
    """Clean transcription text with light touch — preserve meaning."""
    text = _FILLERS_PT.sub("", text)
    text = _REPEATED_WORDS.sub(r"\1", text)
    text = _EXCESS_PUNCT.sub(r"\1", text)
    # Normalize whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_pdf_text(text):
    """Clean PDF-extracted text: de-hyphenate line breaks, normalize whitespace.

    Skips filler/repetition passes since those are tuned for spoken transcripts.
    """
    text = re.sub(r"-\n(\w)", r"\1", text)          # join "exam-\nple" -> "example"
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean(text, source_type):
    """Dispatch to the right cleaner by source type."""
    if source_type == "pdf":
        return clean_pdf_text(text)
    return clean_text(text)
