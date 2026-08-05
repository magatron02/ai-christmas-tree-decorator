"""AC-5 quality run.

Feeds pairs of (bare tree, element) through the real pipeline and collects the results for
a human to grade. It deliberately does not score anything: AC-5 asks whether a result is
"realistic enough to sell", which is a judgement by someone who sells these, not a metric.

    python scripts/run_quality_batch.py ac5-source/pairs.txt

`pairs.txt` is one pair per line, tree and element separated by a tab or a comma:

    ac5-source/trees/norway-spruce.png    ac5-source/elements/red-ball.png

Every run costs money — one billed generation per line. Start with three lines before
committing to thirty, because the thing most likely to be wrong is the inputs.

Writes ac5-results/<stamp>/ containing every output image and an index.html that puts the
three images side by side in the order Product.md asks for: bare tree, element, result.
Failures are recorded and do not stop the batch.
"""

import argparse
import csv
import json
import sys
import urllib.request
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def read_pairs(path):
    pairs = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in (line.split("\t") if "\t" in line else line.split(","))]
        if len(parts) != 2:
            raise SystemExit(f"{path}:{number}: expected 'tree<TAB>element', got {line!r}")
        tree, element = (Path(p) if Path(p).is_absolute() else ROOT / p for p in parts)
        for candidate in (tree, element):
            if not candidate.is_file():
                raise SystemExit(f"{path}:{number}: no such file {candidate}")
        pairs.append((tree, element))
    return pairs


def run_one(client, base, tree, element, size):
    """One pair through the whole pipeline. Returns a result dict, never raises."""
    result = {"tree": tree.name, "element": element.name, "size": size}

    cut = client.post(
        f"{base}/api/remove-bg",
        files=[("files", (element.name, element.read_bytes(), "image/png"))],
    )
    if cut.status_code != 200:
        return result | {"stage": "remove-bg", "error": cut.json().get("error", cut.text)}
    element_name = cut.json()["element"]

    ready = client.post(
        f"{base}/api/prepare",
        files=[("files", (tree.name, tree.read_bytes(), "image/png"))],
        data={"element": element_name, "size": size},
    )
    if ready.status_code != 200:
        return result | {"stage": "prepare", "error": ready.json().get("error", ready.text)}
    request_id = ready.json()["request_id"]
    result["request_id"] = request_id

    done = client.post(f"{base}/api/generate/{request_id}")
    if done.status_code != 200:
        return result | {"stage": "generate", "error": done.json().get("error", done.text)}

    payload = done.json()
    client.post(f"{base}/api/delivered/{request_id}")
    return result | {
        "stage": "done",
        "tree_url": payload["tree_url"],
        "element_url": payload["element_url"],
        "output_url": payload["output_url"],
        "tokens": payload["usage"]["total_tokens"] if payload["usage"] else None,
    }


def fetch(base, url, into):
    into.write_bytes(urllib.request.urlopen(f"{base}{url}").read())
    return into.name


INDEX_HEAD = """<!doctype html>
<meta charset="utf-8">
<title>AC-5 quality run</title>
<link rel="stylesheet" href="../../frontend/styles/factory-tokens.css">
<link rel="stylesheet" href="../../frontend/styles/factory.css">
<style>
  .page { max-width: none }
  .run { margin-bottom: 20px }
  .triptych img { max-height: 420px; width: auto; margin: 0 auto; display: block }
</style>
<main class="page stack">
<h1 class="logo">AC-5 quality run</h1>
<p class="hint">Grade each row: does the result look real enough to show a customer, with no
retry? AC-5 passes at 21 of 30.</p>
"""

RUN = """
<section class="card stack run">
  <span class="caption">{n} — {tree} + {element}</span>
  <div class="triptych">
    <figure><figcaption class="caption">Bare tree</figcaption><img class="thumb" src="{tree_file}"></figure>
    <figure><figcaption class="caption">Element</figcaption><img class="thumb checker" src="{element_file}"></figure>
    <figure><figcaption class="caption">Result</figcaption><img class="thumb" src="{output_file}"></figure>
  </div>
  <span class="hint mono">{request_id} · {size} · {tokens} tokens</span>
</section>
"""

FAILED = """
<section class="card stack run">
  <span class="caption">{n} — {tree} + {element}</span>
  <div class="notice">failed at {stage}: {error}</div>
</section>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pairs", help="file listing tree/element pairs, one per line")
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="running server")
    parser.add_argument("--size", default="4:5")
    parser.add_argument("--out", default="ac5-results")
    parser.add_argument("--stamp", required=True, help="folder name for this run, e.g. pilot-1")
    args = parser.parse_args()

    pairs = read_pairs(args.pairs)
    out = ROOT / args.out / args.stamp
    out.mkdir(parents=True, exist_ok=True)

    print(f"{len(pairs)} pair(s) — one billed generation each. Writing to {out}")

    client = httpx.Client(timeout=900)
    results = []
    body = []

    for n, (tree, element) in enumerate(pairs, 1):
        print(f"[{n}/{len(pairs)}] {tree.name} + {element.name} ... ", end="", flush=True)
        result = run_one(client, args.base, tree, element, args.size)
        results.append(result)

        if result["stage"] != "done":
            print(f"FAILED at {result['stage']}: {result['error']}")
            body.append(FAILED.format(n=n, **result))
            continue

        for key, suffix in (("tree_url", "tree"), ("element_url", "element"), ("output_url", "result")):
            name = f"{n:02d}_{suffix}.png"
            fetch(args.base, result[key], out / name)
            result[f"{suffix}_file"] = name
        print(f"ok — {result['tokens']} tokens")
        body.append(RUN.format(n=n, **result))

    (out / "index.html").write_text(INDEX_HEAD + "".join(body) + "\n</main>\n", encoding="utf-8")
    (out / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")

    with (out / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["n", "tree", "element", "request_id", "stage", "tokens", "passes"])
        for n, result in enumerate(results, 1):
            writer.writerow([
                n, result["tree"], result["element"], result.get("request_id", ""),
                result["stage"], result.get("tokens", ""), "",
            ])

    done = [r for r in results if r["stage"] == "done"]
    tokens = sum(r["tokens"] or 0 for r in done)
    print(f"\n{len(done)}/{len(results)} generated, {tokens:,} tokens total")
    print(f"grade them: {out / 'index.html'}")
    print(f"record verdicts in the 'passes' column of {out / 'results.csv'}")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
