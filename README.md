# rag-data-pipeline

Multi-source RAG knowledge base. Ingest YouTube videos, local audio/video files, and PDFs into ChromaDB — then query them via an interactive chat REPL or any MCP-compatible client.

## What it does

```
discover (URL or local path)
  -> YouTube  (yt-dlp download)
  -> audio/video (local files, any common extension)
  -> PDF      (pypdf text extraction)
-> transcribe (Whisper, auto-scaling pool) OR extract (pypdf)
-> clean -> chunk -> embed (all-MiniLM-L6-v2) -> ChromaDB
-> chat (OpenAI GPT with source attribution)
```

**Key features:**
- **One command** ingests any source type. `make ingest INPUT=<url-or-path>` auto-detects.
- **Multiple isolated knowledge bases** via `DB=./db_name` on every command.
- **Idempotent & resumable.** Each stage reads `data/status.json` and skips already-done work. Failed items land in a DLQ with `make retry`.
- **Auto-scaling Whisper pool.** First worker claims the GPU if it fits; additional workers spawn as system resources allow.
- **Pluggable source layer.** Adding a new source type (Markdown, Confluence, etc.) = one file in `ingest/sources/`.

## Installation

Requires Python 3.10+ and `ffmpeg` on `PATH`.

```bash
git clone https://github.com/lucasribeiro-dev/rag-data-pipeline.git
cd rag-data-pipeline
cp .env.example .env        # add your OPENAI_API_KEY
make setup
```

## Usage

```bash
make help                                              # self-documenting target list

# Ingest — one flag for any source
make ingest INPUT=https://youtube.com/watch?v=xyz      # YouTube video
make ingest INPUT=https://youtube.com/@channel         # whole channel
make ingest INPUT=/path/to/folder                      # mixed mp3/mp4/pdf dir
make ingest INPUT=/path/to/book.pdf TYPE=pdf           # single file, forced type

# Separate knowledge bases per topic
make ingest INPUT=./crypto_videos DB=./db_crypto
make ingest INPUT=./engineering_books DB=./db_eng

# Query
make chat  DB=./db_eng                                 # interactive RAG chat
make stats DB=./db_eng                                 # pipeline + DB stats
```

### Supported inputs

| Type | Extensions / detection |
|---|---|
| YouTube | URLs matching `youtube.com` / `youtu.be` |
| Audio | `.mp3 .wav .m4a .flac .ogg` |
| Video | `.mp4 .mkv .webm .avi .mov` |
| PDF | `.pdf` (text-layer PDFs; scanned PDFs fail with a clear OCR-needed message) |

## Configuration

All settings in `.env` (copy from `.env.example`). Key vars:

| Var | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | *(required)* | For the chat REPL |
| `OPENAI_MODEL` | `gpt-4o` | Chat completion model |
| `WHISPER_MODEL` | `large` | `tiny`/`base`/`small`/`medium`/`large` — larger = slower + better |
| `CHUNK_SIZE` | `500` | Words per chunk |
| `CHUNK_OVERLAP` | `50` | Overlap between chunks |
| `TOP_K_RESULTS` | `5` | Chunks retrieved per query |
| `CHROMA_DB_PATH` | `./db` | Default vector DB path |

## Architecture

```
scripts/ingest.py            # unified orchestrator
    detect_source() -> Source (YouTube | Media | PDF)
    source.discover() -> Items
    Items with audio/video -> ingest.transcribe.transcribe_auto()  (Whisper pool)
    Items with pdf         -> source.extract_text()                (pypdf)
    -> scripts/store.py                                            (clean -> chunk -> embed)

scripts/chat.py              # interactive REPL -> bot.rag.RAGBot -> OpenAI
scripts/stats.py             # pipeline + DB stats, by source_type
```

See [`CLAUDE.md`](CLAUDE.md) for the full module map and design decisions.

## Claude Code / MCP integration

This repo intentionally does not ship its own MCP server — use the official [`chroma-mcp`](https://github.com/chroma-core/chroma-mcp) instead:

```bash
claude mcp add chroma-db -- uvx chroma-mcp --client-type persistent --data-dir ./db
```

Make sure the MCP server uses the same embedding model (`all-MiniLM-L6-v2`) as the pipeline, otherwise retrieval quality degrades.

## Design decisions worth knowing

- **Item keys are `{source_type}__{slug}`** (`youtube__foo`, `pdf__book_ch1`). Prevents collisions across sources. Legacy bare-keyed YouTube entries still resolve via a `get()` fallback.
- **PDFs skip Whisper entirely.** Extracted text is written directly to `data/transcriptions/` and the item is marked transcribed.
- **Local media is read in place.** `scripts/transcribe.py` uses the original file path (stored as `source_path`) — no copying into `data/audio/`.
- **Changing the embedding model is breaking.** Existing chunks embedded with `all-MiniLM-L6-v2` are incompatible with any other model. If you must switch, rebuild the DB.

## License

MIT
