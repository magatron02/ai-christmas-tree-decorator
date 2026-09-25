# The Excel catalogue zip is how product data gets in

Product data used to be extracted from the shop's printed PDF catalogue (scripts/extract_catalog.py,
scripts/rebuild_catalog_from_books.py). That kept producing errors a person then had to find:
wrong codes, photos that belonged to another code, poor crops, one photo claimed by several codes.
The shop's own copy of its product data is now a zip holding `products.xlsx` and an `images/`
folder, exported from and imported into the settings page's catalogue tab
(`backend/services/catalog_xlsx.py`). A person fills it in and checks it; the app never guesses
from it.

One row per code: code, name, photos (file names; several separated by `;` are that code's
colours, ADR-0002), colour names, main category, sub-category (`section`), pieces per pack, size,
price, book. Sizes are free text in any unit the app can read (`catalog.parse_size`, which now
understands Thai units too); one it cannot read stays unknown rather than guessed.

## Consequences

- Import replaces the whole catalogue base except MS Natural Design, whose rows come from the
  shop's own stock export and are left exactly as they are. A preview comes first; a package with
  any row error cannot be applied, since a rejected row of an existing product would silently
  delete it. The catalogue and both overlays are backed up to `data/backups/` before writing, and
  imported photos get new content-hashed names, so nothing on disk is deleted and a backup restores
  the old catalogue whole.
- The sheet owns every field it carries for the codes it imports: older shop-overlay opinions on
  those fields (and a shop photo or colour split) are dropped. Codes it leaves out keep their
  overlay and show as orphan products (ADR-0001).
- A row may state its category outright; `catalog.category_of` uses it before any keyword guess.
  A row may carry a name; it is shown before the supplier's name.
- Prices are imported into the vendor overlay, where prices are edited and read first; the export
  writes the price a quote actually uses.
- Photos that came in this way are trusted like a shop photo: none of the PDF-crop checks (shared
  crop, page furniture, a code printed twice) describe them.
- It runs in-process with no scripts, so it works from an installed copy. The photo-search index is
  not rebuilt by an import; a sync on a source checkout does that.
- The PDF extractor stays as a legacy tool. "The purge" (wiping every product except MS Natural
  Design so products can be re-checked one by one) is a separate, owner-triggered step that this
  import is built to be used after.
