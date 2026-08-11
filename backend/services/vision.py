"""Describe a decoration in words, so pictures can be compared as text.

Product.md 8.3c has to answer "what in this customer's photo do we sell?". OpenAI has no
image-embedding endpoint — `embeddings.create` takes text only — so the route is: describe
every catalogue photo once, describe the decorations in the customer's photo, and compare
the descriptions.

Describing into fixed fields rather than prose is deliberate. "Red glossy sphere, single"
matches "red glossy sphere, single" whatever words a free-form description happened to pick,
and a field that comes back empty is visibly missing rather than quietly absent from a
sentence.

Nothing here decides anything. It produces attributes; matching and the refusal threshold
live in backend/services/matching.py, and NonGoals.md 7 requires the photo to travel with
the code all the way to the screen.
"""

import base64
from typing import Literal

from pydantic import BaseModel, Field

from backend import config

# "tree" and "banner" were missing from the first version, so a whole Christmas tree came
# back classified as a tree topper. An enum without the right box does not produce a blank;
# it produces a confident wrong answer.
KINDS = Literal[
    "tree", "bauble", "ornament", "ribbon", "bow", "garland", "wreath", "swag", "tinsel",
    "honeycomb", "banner", "star", "tree_topper", "figure", "lights", "gift_box", "lantern",
    "flower", "pick", "bell", "other",
]
FINISHES = Literal[
    "glossy", "matte", "mirror", "glitter", "frosted", "transparent", "metallic",
    "fabric", "natural", "mixed",
]
PACKAGING = Literal["single", "multipack", "display", "unclear"]


class Decoration(BaseModel):
    kind: KINDS
    primary_colour: str = Field(description="one plain colour word, lowercase")
    other_colours: list[str] = Field(default_factory=list)
    finish: FINISHES
    shape: str = Field(description="sphere, teardrop, onion, star, cone, spray, ring, ...")
    pattern: str = Field(
        default="",
        description="stripes, glitter dots, snowflakes, plain. Use an empty string if there "
                    "is no pattern — never the word null.",
    )
    packaging: PACKAGING
    summary: str = Field(description="one short line a shop assistant would say")


class DecorationList(BaseModel):
    decorations: list[Decoration]


CATALOGUE_PROMPT = (
    "This is one product photo from a Christmas decoration catalogue. Describe the product "
    "shown. If the photo shows a retail pack of several, describe the item inside it and set "
    "packaging accordingly. Describe only what is visible; do not guess a size."
)

REFERENCE_PROMPT = (
    "This is a customer's photo of a decorated Christmas tree or display. List the distinct "
    "kinds of decoration hanging on or placed around it — one entry per kind, not per copy. "
    "Ignore the tree itself, the room, furniture, people and packaging. Describe only what is "
    "clearly visible; if you cannot tell what something is, leave it out rather than guessing."
)


# What a crop turned out to be. The pairing script takes the nearest photo to each printed
# code, so where it misfires it hands back whatever else was on the page.
CROP_KINDS = Literal[
    "product",        # an actual item for sale, photographed for the catalogue
    "page_number",    # the printed page-number badge
    "logo",           # the wholesaler's brand mark / pennant
    "heading",        # section or category heading artwork, text rather than merchandise
    "caption",        # a code/size/price ribbon printed beside a product
    "multiple",       # several different products in one frame; identifies none of them
    "blank",          # empty, or a sliver of background with nothing in it
    "unclear",
]


class CropVerdict(BaseModel):
    is_product: bool = Field(
        description="true only if this is a single sellable item photographed for sale"
    )
    crop_kind: CROP_KINDS
    why: str = Field(description="one short line, in English, naming what is actually in frame")


# Deliberately not the catalogue prompt. That one says "describe the product shown", which
# presupposes there is one — asked that way the model called a printed page number "an orange
# circular decoration with the number 44", which is how these got into the picker in the first
# place. This prompt has to make "there is no product here" an easy answer to give.
CROP_AUDIT_PROMPT = (
    "This image was cropped automatically from a printed wholesale catalogue page, by taking "
    "whatever artwork sat nearest to a product code. Sometimes it caught the product. Often it "
    "caught something else on the page.\n\n"
    "Say what is actually in this frame. It is NOT a product if it is: a page-number badge (a "
    "plain disc or square with a number), the company logo or brand pennant, section heading "
    "text or decorative lettering, a caption/price ribbon showing codes and dimensions, a grid "
    "or montage of several different products at once, or blank background.\n\n"
    "It IS a product only if a single sellable decoration is photographed as the subject. Note "
    "that this catalogue genuinely sells printed banners and greeting signs, so text on the "
    "item does not by itself make it page furniture — judge whether the text is the merchandise "
    "or the page's own printing.\n\n"
    "When in doubt, answer unclear rather than guessing product."
)


def _client():
    from openai import OpenAI

    return OpenAI(timeout=config.API_TIMEOUT_S)


def _image_part(image_bytes, mime="image/png"):
    encoded = base64.b64encode(image_bytes).decode()
    return {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}"}


def describe(image_bytes, prompt, mime="image/png"):
    """Returns (DecorationList, usage). Raises nothing special — the caller decides what a
    failed description means, and for the catalogue index it means "skip this one"."""
    response = _client().responses.parse(
        model=config.VISION_MODEL,
        input=[{"role": "user", "content": [{"type": "input_text", "text": prompt},
                                            _image_part(image_bytes, mime)]}],
        text_format=DecorationList,
    )
    usage = response.usage
    return response.output_parsed, {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }


def describe_catalogue_photo(image_bytes, mime="image/png"):
    return describe(image_bytes, CATALOGUE_PROMPT, mime)


def describe_reference(image_bytes, mime="image/png"):
    return describe(image_bytes, REFERENCE_PROMPT, mime)


def audit_crop(image_bytes, mime="image/png"):
    """Returns (CropVerdict, usage). Answers "is this a product at all", which is a different
    question from describe_catalogue_photo's "describe the product"."""
    response = _client().responses.parse(
        model=config.VISION_MODEL,
        input=[{"role": "user", "content": [{"type": "input_text", "text": CROP_AUDIT_PROMPT},
                                            _image_part(image_bytes, mime)]}],
        text_format=CropVerdict,
    )
    usage = response.usage
    return response.output_parsed, {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }


def as_text(decoration):
    """The line that gets embedded. Fixed order so two identical products produce identical
    text regardless of how the model worded the summary."""
    parts = [
        decoration.kind.replace("_", " "),
        decoration.primary_colour,
        *decoration.other_colours,
        decoration.finish,
        decoration.shape,
        decoration.pattern,
        decoration.packaging,
    ]
    # models fill an empty optional field with a placeholder rather than leaving it out —
    # seen so far: "null", "?", "unclear". Embedded as-is they become a fake attribute that
    # every other placeholder-carrying product then matches on.
    empty = {"null", "none", "n/a", "?", "unknown", "unclear", "-", ""}
    return ", ".join(p for p in parts if p and p.strip().lower() not in empty)
