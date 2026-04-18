# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Multi-source RAG knowledge base. Ingests content from YouTube URLs AND local files (`.mp3`, `.mp4`, `.pdf`, and other audio/video extensions), transcribes audio/video locally with Whisper or extracts text from PDFs, chunks and embeds text into ChromaDB, then answers questions via OpenAI GPT with source attribution. Multiple ChromaDB databases can coexist (e.g. one per topic) and be selected at query time via `--db`.

## Commands

```bash
make setup                                              # create venv + install deps
make ingest INPUT=https://youtube.com/...               # full pipeline, auto-detects source
make ingest INPUT=/path/to/folder DB=./db_docs          # local mixed mp3/mp4/pdf dir
make ingest INPUT=/path/file.pdf TYPE=pdf               # single file, forced type
make chat          DB=./db_docs                         # interactive chat against a DB
make stats         DB=./db_docs                         # pipeline + DB stats
make clean                                              # remove venv, data/, db/

# Stage-only helpers (usually only needed for re-runs / DLQ):
make download    URL=https://... TYPE=channel           # YouTube-only, TYPE: channel|video|playlist
make transcribe                                         # transcribe anything still pending
make retry                                              # retry failed transcriptions in DLQ
make store       DB=./db_docs                           # store pending transcriptions
```

`make ingest` accepts `TYPE=auto|youtube|media|audio|video|pdf` to override auto-detection.
`DB=` overrides `CHROMA_DB_PATH` for this run. For the MCP server, set the `CHROMA_DB_PATH` env var in your MCP client config.

## Architecture

Three-stage pipeline with centralized status tracking (`data/status.json`). Each stage is idempotent — checks status before processing, skips already-done work, safe to re-run after failures.

```
discover (Source) → fetch/extract (yt-dlp | Whisper | pypdf) → clean → chunk → embed → chromadb
```

`scripts/ingest.py` is the unified orchestrator. It picks a `Source` (YouTube / media / PDF), registers discovered items in status, runs Whisper once across all media items (model loaded once per run) and pypdf sequentially on any PDFs, then shells to `scripts/store.py` for the embed/store phase.

**Scripts** (`scripts/`):
- `ingest.py` — unified orchestrator (`--input` URL or path, `--type`, `--db`)
- `download.py`, `transcribe.py`, `store.py` — stage-only entry points used by `make download|transcribe|retry|store`
- `chat.py` — interactive RAG REPL (`--db` selects the DB)
- `stats.py` — pipeline + vector-DB stats, broken down by source_type

**Sources** (`ingest/sources/`): pluggable layer; new source types plug in by subclassing `Source` and calling `register()` in `__init__.py`.
- `base.py` — `Source`, `Item` dataclass, `SOURCE_REGISTRY`, `detect_source`, helpers (`slug`, `short_hash`)
- `youtube.py` — wraps `ingest/youtube.py` (yt-dlp)
- `media.py` — local audio (`.mp3/.wav/.m4a/.flac/.ogg`) and video (`.mp4/.mkv/.webm/.avi/.mov`), walks dirs recursively
- `pdf.py` — `pypdf` text extraction; fails an item with `"no text layer — needs OCR"` if >50% of pages yield empty text

**Modules map to pipeline stages:**
- `ingest/youtube.py` — yt-dlp wrapper, metadata extraction (used by `sources/youtube.py`)
- `ingest/transcribe.py` — auto-scaling multiprocess Whisper pool (`AutoScaleTranscriber`, `transcribe_auto`)
- `ingest/cleaner.py` — `clean_text` (spoken-transcript fillers) + `clean_pdf_text` (de-hyphenation) + `clean(text, source_type)` dispatcher
- `processing/chunker.py` — sentence-boundary-aware chunking with word overlap
- `storage/vector_store.py` — ChromaDB wrapper with SentenceTransformer embeddings (`all-MiniLM-L6-v2`)
- `storage/status.py` — JSON status tracker (downloaded/transcribed/stored per item); `get()` has lazy `youtube__` fallback so legacy bare-keyed entries still resolve
- `bot/rag.py` — retrieval + OpenAI completion with chat history
- `bot/prompts.py` — system prompt template
- `mcp_server.py` — FastMCP server exposing `search_knowledge_base` and `knowledge_base_stats`; reads `CHROMA_DB_PATH` from env

**Key design decisions:**
- Items are keyed `{source_type}__{slug}` (e.g. `youtube__Foo`, `pdf__report_ch1`, `audio__lesson_01`). `slug` uses `yt_dlp.utils.sanitize_filename`; path separators flatten to `_`. Collision guard appends a 6-char sha1 prefix when slugs clash inside one source.
- Pre-refactor YouTube entries have bare keys (no prefix). `Status.get(key)` tries the bare key first, then `youtube__{key}` — legacy and new coexist without migration.
- PDF items skip Whisper entirely: the orchestrator writes their extracted text directly to `data/transcriptions/{safe_key}.txt` and marks them transcribed. `scripts/transcribe.py` also filters out `source_type=="pdf"` defensively.
- Media items read directly from their absolute path (`Status.source_path`) — no copying into `data/audio/` for local files. `scripts/transcribe.py` falls back to `{audio_dir}/{safe_title}.mp3` when `source_path` is empty (legacy YouTube behavior).
- Vector store deduplicates by ID (`{source}_{chunk_index}`). Changing the key scheme for a previously-ingested item produces duplicate chunks — avoid re-ingesting old YouTube URLs into the same DB.
- Chat history is capped at 20 messages (10 turns) in memory.
- Whisper model is loaded once per run and reused across all media files (from YouTube + local combined).
- Each ChromaDB directory is an independent knowledge base — use `DB=` to segregate by topic.

## Configuration

All settings in `.env`, loaded by `config.py`. Key vars: `OPENAI_API_KEY`, `OPENAI_MODEL` (gpt-4o), `WHISPER_MODEL` (large), `CHUNK_SIZE` (500), `CHUNK_OVERLAP` (50), `TOP_K_RESULTS` (5), `CHROMA_DB_PATH` (./db), `AUDIO_DIR` (data/audio), `TRANSCRIPTIONS_DIR` (data/transcriptions), `STATUS_FILE` (data/status.json).
