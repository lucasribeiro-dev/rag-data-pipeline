.DEFAULT_GOAL := help
.PHONY: help setup install ingest download transcribe retry store chat stats \
        clean clean-venv clean-data clean-db clean-cache clean-all

VENV   := .venv
PYTHON := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip

## help: Show this help message
help:
	@echo "Usage: make <target> [VAR=value]..."
	@echo ""
	@echo "Targets:"
	@awk '/^## [a-zA-Z][a-zA-Z0-9_-]*:/ { line=$$0; sub(/^## /,"",line); i=index(line,":"); name=substr(line,1,i-1); desc=substr(line,i+2); printf "  \033[36m%-12s\033[0m %s\n", name, desc }' $(MAKEFILE_LIST)
	@echo ""
	@echo "Common usage:"
	@echo "  make setup                                 # install dependencies"
	@echo "  make ingest INPUT=https://youtube.com/...  # full pipeline (URL or path)"
	@echo "  make ingest INPUT=./docs DB=./db_docs      # local dir to a specific DB"
	@echo "  make chat  DB=./db_docs                    # chat against a specific DB"
	@echo "  make stats DB=./db_docs                    # per-DB stats"

## setup: Create venv and install dependencies
setup: $(VENV)/bin/activate

$(VENV)/bin/activate: requirements.txt
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@touch $(VENV)/bin/activate

## install: Alias for setup
install: setup

# --- Full unified pipeline (YouTube URL or local path) ---

## ingest: Full pipeline — INPUT=<url-or-path> [TYPE=...] [DB=...]
ingest: setup
	@test -n "$(INPUT)" || (echo "Usage: make ingest INPUT=<url-or-path> [TYPE=auto|youtube|media|audio|video|pdf] [DB=...]" && exit 1)
	$(PYTHON) scripts/ingest.py --input "$(INPUT)" \
		$(if $(TYPE),--type "$(TYPE)") \
		$(if $(DB),--db "$(DB)") \
		$(if $(STATUS),--status "$(STATUS)") \
		$(if $(AUDIO_DIR),--audio-dir "$(AUDIO_DIR)") \
		$(if $(TRANSCRIPTIONS_DIR),--transcriptions-dir "$(TRANSCRIPTIONS_DIR)") \
		$(if $(MODEL),--model "$(MODEL)") \
		$(if $(WORKERS),--workers "$(WORKERS)") \
		$(if $(MAX_WORKERS),--max-workers "$(MAX_WORKERS)") \
		$(if $(LIMIT),--limit "$(LIMIT)") \
		$(if $(MAX_DEPTH),--max-depth "$(MAX_DEPTH)")

# --- Individual stages (YouTube-only helpers; useful for re-runs) ---

## download: YouTube-only — URL=... [TYPE=channel|video|playlist]
download: setup
	@test -n "$(URL)" || (echo "Usage: make download URL=https://youtube.com/... TYPE=channel|video|playlist" && exit 1)
	$(PYTHON) scripts/download.py --$(or $(TYPE),video) "$(URL)" \
		$(if $(OUTPUT),--output "$(OUTPUT)") \
		$(if $(STATUS),--status "$(STATUS)")

## transcribe: Transcribe anything still pending
transcribe: setup
	$(PYTHON) scripts/transcribe.py --workers $(or $(WORKERS),2) \
		$(if $(INPUT),--input "$(INPUT)") \
		$(if $(OUTPUT),--output "$(OUTPUT)") \
		$(if $(STATUS),--status "$(STATUS)")

## retry: Retry failed transcriptions in DLQ
retry: setup
	$(PYTHON) scripts/transcribe.py --retry --workers $(or $(WORKERS),2) \
		$(if $(INPUT),--input "$(INPUT)") \
		$(if $(OUTPUT),--output "$(OUTPUT)") \
		$(if $(STATUS),--status "$(STATUS)")

## store: Store pending transcriptions — [DB=...]
store: setup
	$(PYTHON) scripts/store.py \
		$(if $(INPUT),--input "$(INPUT)") \
		$(if $(STATUS),--status "$(STATUS)") \
		$(if $(DB),--db "$(DB)")

# --- Chat & utils ---

## chat: Interactive RAG chat — [DB=...]
chat: setup
	$(PYTHON) scripts/chat.py $(if $(DB),--db "$(DB)")

## stats: Pipeline + vector-DB stats — [DB=...]
stats: setup
	$(PYTHON) scripts/stats.py $(if $(DB),--db "$(DB)") $(if $(STATUS),--status "$(STATUS)")

# --- Cleanup (granular + safe by default) ---

## clean-cache: Remove Python bytecode caches
clean-cache:
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +

## clean-venv: Remove the virtualenv
clean-venv:
	rm -rf $(VENV)

## clean-data: Remove downloaded audio + transcriptions + status (KEEPS vector DBs)
clean-data:
	rm -rf data/

## clean-db: Remove ALL vector databases (default + db_*)
clean-db:
	rm -rf db/ db_*/

## clean: Safe default — only bytecode caches
clean: clean-cache

## clean-all: Remove venv, caches, data/, AND all vector DBs (destructive)
clean-all: clean-cache clean-venv clean-data clean-db
