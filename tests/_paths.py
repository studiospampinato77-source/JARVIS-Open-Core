import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("JARVIS_DATA_DIR", tempfile.mkdtemp(prefix="jarvis_tests_"))
for sub in ("ARMS/RESEARCH", "ARMS/WORLD", "ARMS/SOURCES", "CORE", "BENCH"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)
