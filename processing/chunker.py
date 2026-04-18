import re


def _split_sentences(text):
    """Split text into sentences, keeping the delimiter attached."""
    # Split on sentence-ending punctuation followed by space or end of string
    parts = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in parts if s.strip()]


def chunk_text(text, chunk_size=500, overlap=50):
    """Split text into chunks of approximately chunk_size words with overlap.

    Respects sentence boundaries — never cuts mid-sentence.
    Returns a list of text chunks.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return []

    chunks = []
    current_words = []
    current_count = 0

    for sentence in sentences:
        words = sentence.split()
        word_count = len(words)

        # If adding this sentence exceeds chunk_size and we already have content,
        # finalize the current chunk
        if current_count + word_count > chunk_size and current_count > 0:
            chunks.append(" ".join(current_words))

            # Calculate overlap: take the last `overlap` words as the start of next chunk
            if overlap > 0 and len(current_words) > overlap:
                current_words = current_words[-overlap:]
                current_count = len(current_words)
            else:
                current_words = []
                current_count = 0

        current_words.extend(words)
        current_count += word_count

    # Don't forget the last chunk
    if current_words:
        chunks.append(" ".join(current_words))

    return chunks
