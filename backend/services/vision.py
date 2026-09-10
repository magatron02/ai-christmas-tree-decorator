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
#
# santa/snowman/nutcracker/angel/elf/reindeer/teddy_bear used to all collapse into one
# "figure" bucket — measured, that is exactly how a nutcracker matched a Santa at 0.82:
# same kind, and "shape" alone wasn't specific enough to tell them apart. "figure" stays as
# the catch-all for a figure that is none of these, not as the default every figure lands in.
KINDS = Literal[
    "tree", "bauble", "ornament", "ribbon", "bow", "garland", "wreath", "swag", "tinsel",
    "honeycomb", "banner", "star", "tree_topper",
    "santa", "snowman", "nutcracker", "angel", "elf", "reindeer", "teddy_bear", "figure",
    "lights", "gift_box", "lantern", "flower", "pick", "bell", "other",
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


class ColourName(BaseModel):
    name_th: str = Field(
        description="the colour of this item, in Thai, the way a shop assistant would say it "
        "out loud to a customer — one word or a short phrase, e.g. แดง, เขียวเข้ม, ทองแชมเปญ"
    )


# One product code photographed across its whole colour range, split into one photo per
# colour (ADR-0002) — this names the colour in THIS one photo, never the product itself, and
# never in English: the name is for a shop assistant to say and a customer to hear, not a
# database key.
COLOUR_NAME_PROMPT = (
    "This is one photo of a single Christmas decoration, cropped from a strip that shows the "
    "same product across several colours. Name only the colour of the item in THIS photo, in "
    "Thai — the way a shop assistant would say it when a customer points at this exact one. "
    "One word or a short phrase, not a sentence, and not the product's name or kind."
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


class CountedItem(BaseModel):
    code: str = Field(description="the catalogue code exactly as given in its reference label")
    count: int = Field(
        description="how many separate copies of this exact reference decoration are visible "
        "in the finished photo"
    )


class DecorationCounts(BaseModel):
    items: list[CountedItem]


# Counting the picture, not the catalogue. catalog.scale_sentence tells the model how big a
# decoration should be, but measured it renders them at 0.55-0.70x of the instructed ratio
# (scripts/measure_scale.py), so the number of pieces that fit in the finished picture is not
# the number the sizes predict — a 457 mm tree with 279 mm flowers works out at 1-2 by
# arithmetic while the generated image happily shows a dozen. The shop quotes from the picture
# the customer is looking at, so the picture is what has to be counted.
#
# "Only what you can see" is the whole discipline here: the back of the tree is not in frame,
# and a total that silently doubled the visible count to allow for it would be an invented
# number (NonGoals.md 8). The caller says plainly that this is the front-facing count; a
# separate, user-set multiplier for the unseen side lives in the pricing panel, not here.
#
# Counting is per catalogue code, not per free-text "kind" — an earlier version asked the
# model to name and count whatever it saw, which read fine but gave the caller no way to say
# which counted thing was which product. Feeding each accepted decoration's own cut-out photo
# in as a labelled reference lets the model match against the actual products used instead of
# guessing from a category name.
COUNT_PROMPT_HEADER = (
    "Each reference image below shows one specific Christmas decoration, labelled with its "
    "catalogue code. After the references comes a photo of a finished, decorated Christmas "
    "tree that was composited using exactly these decorations.\n\n"
    "For every reference code, count how many separate copies of that exact decoration are "
    "visible in the finished tree photo. Count only copies you can actually see — do not add "
    "anything for copies that would be hidden behind branches or around the back of the tree, "
    "and do not round to a convenient number. If a reference code does not appear at all in "
    "the finished photo, report it with count 0.\n\n"
    "Return exactly one entry per reference code given below, using the code exactly as "
    "labelled. Ignore anything in the finished photo that is not one of the given reference "
    "codes — the tree itself, its stand, the background, or any other object — do not invent "
    "extra entries for it."
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


def name_colour(image_bytes, mime="image/png"):
    """Returns (ColourName, usage) — issue #14's seeding pass, one call per colour photo. A
    separate call from describe_catalogue_photo: that one describes a whole colour strip in
    one go (one primary colour plus a list of others) and cannot say which photo is which."""
    response = _client().responses.parse(
        model=config.VISION_MODEL,
        input=[{"role": "user", "content": [{"type": "input_text", "text": COLOUR_NAME_PROMPT},
                                            _image_part(image_bytes, mime)]}],
        text_format=ColourName,
    )
    usage = response.usage
    return response.output_parsed, {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }


def describe_reference(image_bytes, mime="image/png"):
    return describe(image_bytes, REFERENCE_PROMPT, mime)


def count_decorations(image_bytes, references, mime="image/png"):
    """Returns (DecorationCounts, usage) — how many of each referenced code are visible in a
    finished picture. `references` is a list of (code, image_bytes, mime) for every accepted
    decoration that has a catalogue code — the same cut-outs the compositor was given, fed
    back in as labelled reference photos so the count can be attributed to a code instead of
    a free-text guess. Billed, so nothing calls this on its own; the user asks for it."""
    content = [{"type": "input_text", "text": COUNT_PROMPT_HEADER}]
    for code, ref_bytes, ref_mime in references:
        content.append({"type": "input_text", "text": f"Reference code: {code}"})
        content.append(_image_part(ref_bytes, ref_mime))
    content.append({"type": "input_text", "text": "Finished tree photo:"})
    content.append(_image_part(image_bytes, mime))

    response = _client().responses.parse(
        model=config.VISION_MODEL,
        input=[{"role": "user", "content": content}],
        text_format=DecorationCounts,
    )
    usage = response.usage
    return response.output_parsed, {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }


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
