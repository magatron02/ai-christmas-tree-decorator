# The catalogue is a read-only base plus a shop-owned overlay, merged per field

The catalogue is extracted from the shops' printed books and regenerated wholesale whenever a book
is re-imported, but the shop now needs to own parts of that data itself — prices (638 of 829
products have none), its own photographs of products whose book crop is unusable, corrected
details, and colour names. Keeping both in one file has already destroyed work once: the re-import
on 2026-08-19 wiped `catalog/variants.json` from 264 codes down to `{}`, orphaning 919 colour
images that are still on disk. So shop-owned values live in a separate overlay that no re-import
touches, and a product record is the base merged with the overlay **field by field** — the shop's
price wins while an unedited size still follows the book, so re-importing a corrected book still
delivers its corrections.

## Consequences

- A code that disappears from every base while an overlay still exists is kept and flagged as an
  orphan, never deleted silently — the shop paid for that work with its own time.
- The code itself is not overlayable: it is the key the overlay, the generation history and the
  staff worksheet all join on. A wrong code is fixed by deleting the product and creating it again.
- `bbox` and `pdf_page` stay base-only and are never shown; they describe a position in a PDF, not
  a product.
