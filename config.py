import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
TOP_K_RESULTS = int(os.getenv("TOP_K_RESULTS", "5"))
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "./db")
AUDIO_DIR = os.getenv("AUDIO_DIR", "data/audio")
TRANSCRIPTIONS_DIR = os.getenv("TRANSCRIPTIONS_DIR", "data/transcriptions")
STATUS_FILE = os.getenv("STATUS_FILE", "data/status.json")
