# Tree Decorator

A shop decorates a bare Christmas tree for a customer by generating a picture of it, using products
the shop actually sells. Everything here is vocabulary for talking about that catalogue, those
products, and the ways a tree gets decorated.

## Language

### The catalogue

**Catalogue base**:
The product data extracted from a shop's printed book. Regenerated wholesale every time a book is
re-imported, and never edited by hand.
_Avoid_: catalogue (unqualified), PDF data

**Shop overlay**:
The shop's own corrections to a product, held field by field. Survives every re-import; this is
where a price, a photo, a colour name or a corrected detail lives.
_Avoid_: edits, custom data, user data

**Product record**:
What the app shows for one product: the base merged with the overlay, the overlay winning only on
the fields it actually holds.
_Avoid_: product row, catalogue entry

**Code**:
The shop's identifier for a product, printed in the book. The one field that never changes — a
wrong code is fixed by deleting the product and creating it again.
_Avoid_: SKU, product ID, item number

**Orphan product**:
An overlay whose code no longer appears in any base after a re-import. Kept and flagged, never
silently dropped.

**Price**:
What the shop sells one of these for. Optional — a product with no price is fully usable for
generating a picture; only a total is unavailable.

**Skipped for pricing**:
A product the shop has declared it will never price. Stays usable, and leaves the pricing queue
for good.

### Photos and colours

**Colour**:
One named appearance of a product photographed across a colour range. A colour is a named picture
of a code, not a code of its own — the shop orders "this code, red", not a separate product.
_Avoid_: variant, colourway, sub-SKU

**Colour name**:
The Thai word the shop uses for a colour. Travels with the code into the history and the staff
worksheet, because that is what gets ordered.

**Book photo**:
The crop taken from the printed catalogue. Base layer: it can be superseded by a shop photo, but
never deleted.
_Avoid_: catalogue image, crop

**Shop photo**:
A picture the shop took of the real product. Overlay layer.

**Main photo**:
The one picture of a colour that shows the product completely enough to generate from. Chosen by
the shop, and chosen per colour — never per code.
_Avoid_: primary image, hero shot

**Supporting photo**:
Any other angle of the same colour. Shown to people choosing a product; never sent to the image
model.

**Bad crop**:
A book photo that shows page furniture, or is shared by so many codes that it identifies none of
them. Hides the product from the picker until a shop photo replaces it.

### Decorating a tree

**Tone**:
A named colour direction a customer asks for, such as red-gold classic. The only question Auto
pick asks.

**Recipe**:
The fixed mix of categories and counts placed on every tree. Tone decides which products fill the
recipe; it never changes what the mix is, and neither does the size of the tree.

**Auto pick**:
Choosing a tone and having the app fill the recipe. Produces a proposal in the normal panels for
the shop to review, never a finished picture.
_Avoid_: auto mode, wizard

**Wizard**:
Retired. Formerly a size, budget and category gate in front of Auto pick. Not to be reintroduced
without first solving the price coverage it depended on (ADR-0003).

**Manual size**:
A real measurement typed in by a person for a product whose book never printed one. The app never
guesses this number.

**Density**:
How thickly decorations of one kind are placed on the tree — sparse, normal or packed.

**Custom prompt**:
A free-text description of the wanted result, typed instead of choosing a density. Replaces the
density wording for that one generation, never the rules that keep the tree and background intact.
