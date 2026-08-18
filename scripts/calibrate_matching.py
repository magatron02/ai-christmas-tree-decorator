"""Find the score below which "nothing close" is the honest answer.

    python scripts/calibrate_matching.py

matching.MIN_SCORE decides when the system refuses. Picking it by feel would make the refusal
theatre, and AC-8 asks for a refusal that actually happens. So: score things that are in the
catalogue, score things that plainly are not, and look at where the two groups sit.

The negatives are ordinary objects nobody sells here. If those score as high as real
products, the threshold cannot separate them and the honest conclusion is that this search
is not ready to recommend anything.
"""

import sys

import numpy as np

from _bootstrap import ROOT

from backend.services import matching  # noqa: E402

# things a customer photo of a Christmas display really might contain
POSITIVE = [
    "red glossy round bauble hanging on a tree",
    "gold shiny ball ornament",
    "green shiny sphere decoration with a gold cap",
    "silver mirrored disco ball ornament",
    "wide red ribbon bow",
    "green pine garland along a mantelpiece",
    "gold glitter star tree topper",
    "string of warm white fairy lights",
    "red and gold wrapped gift box under the tree",
    "wreath of green pine with red berries",
]

# things that are not in a Christmas decoration catalogue at all
NEGATIVE = [
    "blue ceramic coffee mug, matte, cylinder",
    "black leather office chair on castors",
    "stainless steel kitchen sink tap",
    "paperback novel lying on a table",
    "yellow plastic hard hat",
    "pair of running shoes, mesh, white",
    "laptop computer, aluminium, open",
    "bunch of fresh bananas",
]


def best_scores(queries):
    codes, matrix = matching._vectors()
    vectors = matching.embed(queries)
    out = []
    for query, vector in zip(queries, vectors):
        scores = matrix @ vector
        order = np.argsort(-scores)[:3]
        out.append((query, float(scores[order[0]]), [codes[i] for i in order]))
    return out


def main():
    print("IN the catalogue")
    positives = best_scores(POSITIVE)
    for query, score, codes in positives:
        print(f"  {score:.3f}  {query[:46]:46} {codes}")

    print("\nNOT in the catalogue")
    negatives = best_scores(NEGATIVE)
    for query, score, codes in negatives:
        print(f"  {score:.3f}  {query[:46]:46} {codes}")

    p = np.array([s for _, s, _ in positives])
    n = np.array([s for _, s, _ in negatives])
    print(f"\npositives: min {p.min():.3f}  median {np.median(p):.3f}  max {p.max():.3f}")
    print(f"negatives: min {n.min():.3f}  median {np.median(n):.3f}  max {n.max():.3f}")

    gap = p.min() - n.max()
    if gap > 0:
        threshold = (p.min() + n.max()) / 2
        print(f"\nthe groups separate by {gap:.3f}; MIN_SCORE = {threshold:.2f} splits them")
    else:
        print(f"\nthe groups OVERLAP by {-gap:.3f}. No threshold separates them, so this "
              f"search cannot honestly refuse and must not be shipped as a recommender.")
    print(f"MIN_SCORE is currently {matching.MIN_SCORE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
