from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))
SCAN_SUBNET = os.getenv("SCAN_SUBNET", "auto")

DATA_DIR = Path.home() / ".netaudit"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "network_audit.db"
