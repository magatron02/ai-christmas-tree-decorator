"""Shared setup every script here needs before it can `from backend... import ...`.

    from _bootstrap import ROOT

Import this first — sys.path only has backend/ importable once it has run, and .env only
has OPENAI_API_KEY loaded once it has run.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
