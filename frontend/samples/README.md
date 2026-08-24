# Sample pictures

Served by the existing `/static` mount (there is no endpoint for these), and offered behind
the "รูปตัวอย่าง" button on the decorate page.

    trees/    three bare trees, from the AC-5 photo set, downscaled and re-encoded
    scenes/   six rooms — pexels.com, Pexels License (free commercially, no attribution)

The point is that a shop opening the app for the first time has neither a cut-out bare-tree
photo nor a room photo to hand: two dead ends before it can generate anything.

A sample is fetched as a blob and then goes through exactly the path a real upload takes —
the tree becomes the File in `state.treeFile`, the room is POSTed to `/api/reference`. Nothing
downstream can tell a sample from a picture the user chose, and a sample tree carries no
catalogue code, the same as any other photo the user supplies.

No room here contains a Christmas tree, deliberately: the reference supplies the setting and
the prompt is told not to copy objects out of it
(`test_the_reference_prompt_forbids_copying_objects_from_it`), so a reference that already had
a tree would be asking the generator to reconcile two. They vary on the thing the reference
actually controls — flat daylight, warm lamplight, and a dark room with one bright window.

Originals live in `ac5-source/` (gitignored, too large to commit); these are the downscaled
copies, ~1.4 MB for the set.
