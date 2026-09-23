# Decorations generalize across any backdrop, not just a tree

Some products the shop sells were never meant to hang from a branch: a garland wraps a trunk, a
gift box or figure sits at a tree's foot, and a wreath or banner mounts to a wall or door — a
backdrop that has no tree in it at all. Rather than build wall/door decorating as a separate,
simpler feature, we're generalizing the existing tone/recipe/density engine to run against either
kind of backdrop, adding **placement** (hung, wrapped, grounded, mounted) as a category property
that decides how a decoration attaches wherever it lands. The alternative — a standalone flow for
wall/door — would have duplicated tone selection, catalogue browsing and generation entirely for a
saving of one abstraction; reuse costs more up front (the prompt engine and recipe model both need
to reason about backdrop and placement, not just categories and counts) but keeps one engine to
tune instead of two.
