# Specification documents

These six were living on the Desktop and briefly went missing mid-project, taking the only
copy of every decision with them. They are in the repository now, so the safety net is git
history rather than one folder.

| file | what it settles |
|---|---|
| `Product.md` | why this exists, who uses it, every decision taken and when |
| `Spec.md` | how it works — data flow, validation, error handling, reconciliation |
| `AcceptanceCriteria.md` | AC-1 to AC-5, pass/fail, no opinions |
| `NonGoals.md` | what must not be built even when it looks like a good idea mid-sprint |
| `TestPlan.md` | what to check before anything that touches money ships |
| `factory-design-system.md` | the visual system every screen follows |

**These copies are canonical.** Edit them here and commit; the Desktop copies are whatever
they were the day they were copied and will drift. Delete those when you are ready to have
one source.

Decisions are amended, not overwritten: a superseded entry stays struck through with the date
and the reason next to its replacement. The point of a decision log is to show what was
believed at the time, which is exactly what gets lost when the old line is deleted.
