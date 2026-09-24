/* "Auto ตามโทน" — the pick-for-me mode, for a customer who doesn't know what they want.
 *
 * One question: the tone. Auto pick fills a fixed recipe of categories and counts — one per
 * backdrop (issue #24: the hung-and-grounded mix for a tree, wreath+banner for a wall or
 * door), the same for every tone and every backdrop of that kind — and writes the result into
 * the store as ordinary decorations. Nothing here touches the DOM: the Auto panel (render.js)
 * draws from the store, and the shared Generate button in the footer makes the picture, so
 * what was picked can be reviewed or refined in "กำหนดเอง" first without any hand-off step.
 *
 * The size/budget/category wizard that used to gate this is gone (ADR-0003): only 191 of 829
 * products carry a price, so the budget question was choosing from a quarter of the catalogue
 * while appearing to search all of it. The tree is the shop's own, chosen in step 1.
 */

/* Cached per backdrop rather than once (issue #24): a wall or door fills a different recipe
 * and offers a different set of tones, so switching backdrop has to fetch again. */
async function loadAutoConfig() {
  const auto = store.auto;
  if (auto.loaded === store.backdrop) return;
  auto.config = await call(`/api/auto/config?backdrop=${encodeURIComponent(store.backdrop)}`);
  auto.loaded = store.backdrop;
  // a tone the previous backdrop offered may be gone from this one
  if (!auto.config.tones.some((t) => t.key === store.tone)) store.tone = null;
}

async function runAutoPick(reshuffle) {
  const auto = store.auto;
  const body = new FormData();
  body.append("tone", store.tone);
  body.append("backdrop", store.backdrop);
  if (reshuffle) for (const code of auto.exclude) body.append("exclude", code);

  try {
    auto.pick = await call("/api/auto/pick", { method: "POST", body });
    auto.pickError = null;
    const codes = auto.pick.decorations.map((d) => d.code);
    if (reshuffle) auto.exclude.push(...codes);
    else auto.exclude = codes;
  } catch (err) {
    auto.pick = null;
    auto.pickError = err.message;
  }
}

function autoCategoryLabel(key) {
  const entry = store.auto.config.recipe.find((r) => r.category === key);
  return entry ? entry.label : key;
}

/* Turns the last pick into cut-out files and makes them the decorations. Both shortfalls
 * (a category with nothing in this tone, or less stock than the recipe asks for) are the same
 * promise kept: fewer items rather than an off-tone substitution, since the tone is the only
 * thing the shop asked for — render.js says which categories came up short. */
async function materialiseAutoPick() {
  const built = [];
  for (const decoration of store.auto.pick.decorations) {
    const body = new FormData();
    body.append("code", decoration.code);
    const result = await call("/api/element/from-catalog", { method: "POST", body });
    built.push({
      name: result.element,
      url: result.element_url,
      code: decoration.code,
      image: null,
      colours: null,
      sizeMm: result.size_mm,
      manualMm: null,
      price: result.price ?? null,
      typedPrice: null,
      density: "normal",
      status: "ready",
    });
  }
  store.decorations = built;
}

async function pickAndApply(reshuffle) {
  const auto = store.auto;
  showError("");
  setStore({ auto: { ...auto, preparing: true } });
  try {
    await runAutoPick(reshuffle);
    if (store.auto.pick && store.auto.pick.decorations.length) await materialiseAutoPick();
  } catch (err) {
    showError(err.message);
  } finally {
    store.auto.preparing = false;
    resetRun();
  }
}

async function chooseTone(key) {
  store.tone = key;
  store.auto.exclude = [];
  await pickAndApply(false);
}

function shuffleAuto() {
  return pickAndApply(true);
}
