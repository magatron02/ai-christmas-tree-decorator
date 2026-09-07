# Retire the wizard: Auto pick asks for a tone and nothing else

Auto pick shipped behind a three-question gate — tree size, budget, category — whose middle
question it could not actually answer: only 191 of 829 products carry a price, and the pool builder
excluded unpriced products outright rather than inventing a number, so a budget filter was choosing
from 23% of the catalogue while appearing to search all of it. The gate is removed. Auto pick now
asks for a tone, fills a fixed recipe of categories and counts, and uses the tone only to filter
which products fill that recipe. Tree size does not change the recipe either: density already
controls how thickly the result is decorated, and an uploaded tree photo has no known size at all.

## Consequences

- Unpriced products become selectable by Auto pick. Nothing is being costed at pick time, so
  excluding them only shrank the choice.
- A tone with no product in some category of the recipe yields fewer items, rather than
  substituting an off-tone product — the tone is the only thing the shop asked for.
- The gate's supporting machinery goes with it (tree-height presets, nearest-tree lookup, foot-to-
  millimetre conversion, the history category counts, the stepper UI and its tests). The pool
  builder survives with its budget and category inputs removed.
- Auto pick still hands its proposal to the normal panels for review before anything is generated;
  a two-click generate would spend real money on a set the shop had not seen.
