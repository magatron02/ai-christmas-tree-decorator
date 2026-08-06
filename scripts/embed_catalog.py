"""Embed every catalogue description so photos can be searched as text.

    python scripts/embed_catalog.py

Cheap and quick — short strings, batched. Run it after scripts/describe_catalog.py, and
again whenever the descriptions change, or search will be answering from a stale catalogue
without saying so.
"""

import json
import sys
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from backend.services import matching  # noqa: E402

CATALOG = ROOT / "catalog"
BATCH = 200


def main():
    rows = json.loads((CATALOG / "descriptions.json").read_text(encoding="utf-8"))
    usable = [row for row in rows.values() if not row.get("error") and row.get("text")]
    print(f"{len(usable)} descriptions to embed ({len(rows) - len(usable)} skipped)")

    codes, vectors = [], []
    for start in range(0, len(usable), BATCH):
        chunk = usable[start : start + BATCH]
        vectors.append(matching.embed([row["text"] for row in chunk]))
        codes.extend(row["code"] for row in chunk)
        print(f"  {len(codes)}/{len(usable)}")

    matrix = np.vstack(vectors)
    np.save(CATALOG / "embeddings.npy", matrix)
    (CATALOG / "embedding_codes.json").write_text(json.dumps(codes), encoding="utf-8")

    print(f"{matrix.shape[0]} vectors of {matrix.shape[1]} dims -> {CATALOG / 'embeddings.npy'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
