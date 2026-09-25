/* Front end for the decorate page: the handlers and the generate pipeline.
 *
 * What is on screen comes from `store` (store.js) via render() (render.js); this file changes
 * the store and calls render()/setStore(), and talks to the server. Two things here are
 * requirements rather than polish:
 *
 *  - The confirm dialog is not optional. Generate never reaches the paid endpoint; it
 *    prepares the request first, then asks (AC-4).
 *  - Preparing before the dialog is deliberate. The dialog is bound to one request_id, so
 *    a double-click on Confirm hits the same id and the server refuses the second call.
 *    Preparing after the dialog would mint a second id and buy a second image.
 *
 * The tiles show what has been spent, not what is left. OpenAI does not tell an API key how
 * much money remains in the account, so a "balance" here would be a number kept by hand and
 * wrong the moment anything else used the same key.
 */

const $ = (id) => document.getElementById(id);

const STATE_LABEL = {
  pending: ["", "พร้อมสร้างภาพ"],
  calling_api: ["running", "กำลังสร้างภาพ…"],
  api_success: ["done", "ได้ภาพแล้ว"],
  api_failed: ["failed", "สร้างไม่สำเร็จ — ไม่ถูกคิดเงิน"],
  delivered: ["done", "ส่งถึงแล้ว"],
};

// A code-bearing item (tree or element) whose catalogue row has no size, and that has not
// been given a manual one yet — the thing the blocking gate exists to stop. NonGoals.md 8:
// the app must not guess this number, so Generate simply cannot be pressed until it is filled.
function needsManualSize(code, sizeMm, manualMm) {
  return Boolean(code) && sizeMm == null && manualMm == null;
}

function anyManualSizeMissing() {
  const base = store.base;
  return Boolean(base && needsManualSize(base.code, base.sizeMm, base.manualMm))
    || store.decorations.some((e) => needsManualSize(e.code, e.sizeMm, e.manualMm));
}

/* What Generate is still waiting for, in the words the footer shows under the button (SPEC §5).
 * Empty means it can go. One list serves every mode, so the button and its reason cannot disagree. */
function missingForGenerate() {
  const missing = [];
  if (!store.base) missing.push("ต้น/ผนัง");
  else if (!store.base.file) missing.push("ไฟล์รูปต้น (โหลดใหม่ไม่สำเร็จ)");
  const decorations = store.decorations;
  if (!decorations.length) missing.push("ของตกแต่งอย่างน้อย 1 ชิ้น");
  if (decorations.some((e) => e.status === "cutting")) missing.push("รอตัดพื้นหลังให้เสร็จ");
  if (decorations.some((e) => e.status === "pending")) missing.push("ตัดพื้นหลังของชิ้นที่อัปโหลด");
  if (decorations.some((e) => e.status === "failed")) missing.push("เอาชิ้นที่ตัดไม่สำเร็จออก");
  if (store.mode === "prompt" && !store.prompt.trim()) missing.push("คำอธิบายที่อยากได้");
  if (anyManualSizeMissing()) {
    const codes = [store.base, ...decorations]
      .filter((item) => item && needsManualSize(item.code, item.sizeMm, item.manualMm))
      .map((item) => item.code);
    missing.push(`ขนาดของ ${codes.join(", ")}${store.mode === "auto" ? " (ใส่ในโหมดกำหนดเอง)" : ""}`);
  }
  if (store.auto.preparing) missing.push("รอเตรียมรูป");
  return missing;
}

function setStatus(key, override) {
  const [cls, text] = STATE_LABEL[key] || ["", key];
  const chip = $("status-chip");
  chip.className = cls ? `chip ${cls}` : "chip";
  chip.textContent = override || text;
}

function showError(message) {
  const box = $("error-box");
  box.textContent = message;
  box.hidden = !message;
}

/* Real millimetres need a code on the tree AND on every decoration: the prompt states a
 * ratio between the two, and half of one is not a ratio (catalog.scale_sentence refuses a
 * partial set outright).
 *
 * Codes are no longer typed — they arrive attached to whatever came out of the catalogue
 * picker — so a mixed set (own photo of a tree, catalogue decoration) is now something the
 * user cannot fix by filling a box. Generate stays available in that case and simply sends
 * no codes at all, the same as a run where nothing was picked from the catalogue; the
 * confirm dialog says the sizes will not be exact. Sending the half that exists is the one
 * thing that must not happen — the server refuses it, and it could not produce a ratio
 * anyway. */
function exactScaleReady() {
  return Boolean(store.base && store.base.code) && store.decorations.length > 0
    && store.decorations.every((element) => element.code);
}

const DENSITY_LEVELS = ["light", "normal", "full"];
const DENSITY_LABEL_TH = { light: "โปร่ง", normal: "ปกติ", full: "แน่น" };

/* The markup both inline rows below share: a line of explanation, then a number field with its
 * unit. Only what they have in common lives here — each keeps its own wording, its own reason
 * for being hidden, and its own idea of when the typed value counts.
 *
 * The unit is a fixed label (a price is always บาท) unless the caller passes `unitOptions`
 * (issue #29) — a size can be measured several ways, so that one gets a real `<select>`
 * instead, and the caller reads back whichever unit is currently chosen via `unitEl.value`. */
function buildInlineRow({ warnText, warnClass, unit, unitOptions, min, placeholder, value }) {
  const row = document.createElement("div");
  row.className = "size-input-row";
  const warn = document.createElement("span");
  warn.className = warnClass;
  warn.textContent = warnText;
  const input = document.createElement("input");
  input.className = "input";
  input.type = "number";
  input.min = min;
  input.placeholder = placeholder;
  if (value != null) input.value = value;
  let unitEl;
  if (unitOptions) {
    unitEl = document.createElement("select");
    unitEl.className = "unit";
    // built dynamically, so it never got the fix that gave every static <select> in this app
    // a real name (issue #26's audit) unless it asks for one itself
    unitEl.setAttribute("aria-label", "หน่วยขนาด");
    for (const option of unitOptions) {
      const el = document.createElement("option");
      el.value = option.value;
      el.textContent = option.label;
      unitEl.append(el);
    }
  } else {
    unitEl = document.createElement("span");
    unitEl.className = "unit";
    unitEl.textContent = unit;
  }
  const field = document.createElement("div");
  field.className = "size-input-field";
  field.append(input, unitEl);
  row.append(warn, field);
  return { row, input, warn, unitEl };
}

/* Same mm-per-unit factors catalog.parse_size already uses server-side (backend/services/
 * catalog.py's _MM_PER_INCH / _MM_PER_FOOT) — a shop typing "6 นิ้ว" here and a book printing
 * "6 inc." must land on the same millimetre number either way (issue #29). */
const SIZE_UNITS = [
  { key: "mm", label: "มม.", perMm: 1 },
  { key: "cm", label: "ซม.", perMm: 10 },
  { key: "inch", label: "นิ้ว", perMm: 25.4 },
  { key: "ft", label: "ฟุต", perMm: 304.8 },
];

/* The blocking size-input row + density pill shared by the tree slot and every accepted
 * element — one small builder so the two call sites (renderTreeSizeGate, renderElements)
 * agree on markup and behaviour instead of drifting apart.
 *
 * A tape measure at the counter reads in cm as often as mm, and a shop reaching for a ruler
 * might have inches on it instead — so the unit is a choice (issue #29), not a fixed "มม."
 * label, while the number this row ultimately reports is still always a plain millimetre
 * value: everything downstream (Generate's disabled state, the scale prompt, `manualMm`
 * itself) is unchanged and still only ever sees mm, exactly as before this issue. Rounded to
 * the nearest whole millimetre on conversion — the same precision parse_size itself keeps,
 * not a long decimal that claims more accuracy than a tape measure gives. */
function buildSizeRow(sizeMm, manualMm, onInput) {
  if (sizeMm != null) {
    const hidden = document.createElement("div");
    hidden.className = "size-input-row";
    hidden.hidden = true;
    return hidden;
  }
  const { row, input, warn, unitEl } = buildInlineRow({
    warnText: manualMm != null
      ? `✓ ใช้ ${manualMm} มม. ในการคำนวณสัดส่วน`
      : "ระบบจะไม่เดาขนาดให้ — ใส่ขนาดจริงก่อนสร้างภาพ",
    warnClass: manualMm != null ? "size-ok-text" : "size-warn-text",
    unitOptions: SIZE_UNITS.map((unit) => ({ value: unit.key, label: unit.label })),
    min: "1", placeholder: "เช่น 150", value: manualMm,
  });

  function mmValue() {
    const unit = SIZE_UNITS.find((u) => u.key === unitEl.value) || SIZE_UNITS[0];
    const typed = Number(input.value);
    return input.value && typed > 0 ? Math.round(typed * unit.perMm) : null;
  }
  // Reports the current mm value (or "") to the caller — called on every keystroke AND as
  // part of committing, so both paths agree on exactly one place that turns a null mm into
  // the empty string `onInput` expects.
  function report() {
    const mm = mmValue();
    onInput(mm != null ? String(mm) : "");
    return mm;
  }

  // `report` only updates state + Generate's disabled flag, both of which read state directly
  // and need no DOM of their own — never a re-render of the list this row lives in, which
  // would tear out and rebuild this very input mid-keystroke. Reported live: typing "100" only
  // ever registered the "1", because every keystroke's re-render handed focus to a brand-new
  // node the browser had never actually focused. The confirmation text below still catches up,
  // just on `change` (blur/Enter, or switching the unit) rather than every keystroke, updated
  // in place by `commit`.
  input.addEventListener("input", report);
  function commit() {
    const mm = report();
    const unit = SIZE_UNITS.find((u) => u.key === unitEl.value);
    warn.className = mm != null ? "size-ok-text" : "size-warn-text";
    warn.textContent = mm == null
      ? "ระบบจะไม่เดาขนาดให้ — ใส่ขนาดจริงก่อนสร้างภาพ"
      : unit.key === "mm"
        ? `✓ ใช้ ${mm} มม. ในการคำนวณสัดส่วน`
        : `✓ ใช้ ${input.value} ${unit.label} (${mm} มม.) ในการคำนวณสัดส่วน`;
  }
  input.addEventListener("change", commit);
  unitEl.addEventListener("change", commit);
  return row;
}

/* The same inline treatment as the size row above, for a picked product the book never priced
 * (issue #27) — the shop notices the gap here, mid-pick, and can close it without leaving the
 * picker. Deliberately NOT a gate: a price has never been needed to make a picture
 * (CONTEXT.md), so this never disables Generate, and skipping it costs nothing but a total.
 * `onTyped` gets the raw string on `change` — not `input`, which would fire a save per
 * keystroke — and does the saving, the same division of labour buildSizeRow has.
 *
 * `price` and `typedPrice` split the same way buildSizeRow's two do: a price the product
 * already had hides the row entirely, while one typed here keeps it, showing what was saved.
 * Both states are muted rather than a warning — this is an offer, not the blocking gate. */
function buildPriceRow(code, price, typedPrice, onTyped) {
  if (!code || price != null) {
    const hidden = document.createElement("div");
    hidden.className = "size-input-row";
    hidden.hidden = true;
    return hidden;
  }
  const { row, input } = buildInlineRow({
    warnText: typedPrice != null
      ? `✓ บันทึกราคา ${typedPrice} บาทแล้ว`
      : "ยังไม่มีราคา — ใส่ตอนนี้ก็ได้ ไม่ใส่ก็สร้างภาพได้",
    warnClass: "size-ok-text",
    unit: "บาท", min: "0", placeholder: "ราคา", value: typedPrice,
  });
  input.addEventListener("change", () => {
    if (input.value && Number(input.value) >= 0) onTyped(input.value);
  });
  return row;
}

/* One write path for a price however it was typed (issue #27). Returns the price the server parsed, so the
 * panel shows what was actually saved rather than what was typed at it. */
async function savePrice(code, value) {
  const body = new FormData();
  body.append("price", value);
  const saved = await call(`/api/catalog/products/${encodeURIComponent(code)}/price`, {
    method: "POST", body,
  });
  return saved.price;
}

/* A named colour reads by its name; one nobody has named yet (issue #14's seeding pass ran,
 * or the shop hasn't corrected it) falls back to its position — never invented. Shared by the
 * picker card's label and the switcher's own option text, so the two can't say it two ways. */
function colourLabel(name, position, total) {
  return name || `สี ${position} จาก ${total}`;
}

/* A row of small buttons, one per colour or pattern of a decoration (issue #15), each with its
 * own thumbnail — every option visible at once instead of behind a dropdown. Only ever built
 * for an item whose `colours` came back with more than one entry (a decoration's own "offer a
 * switcher" rule), so callers never have to check that here too. */
function buildColourChips(colours, current, onPick) {
  const wrap = document.createElement("div");
  wrap.className = "colour-chips";
  wrap.setAttribute("role", "group");
  wrap.setAttribute("aria-label", "เลือกสี/ลายก่อนสร้างรูป");
  colours.forEach((colour, index) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "colour-chip";
    chip.setAttribute("aria-pressed", String(colour.image === current));
    const dot = document.createElement("img");
    dot.src = catalogImageUrl(colour.image);
    dot.alt = "";
    chip.append(dot, colourLabel(colour.name, index + 1, colours.length));
    chip.addEventListener("click", () => onPick(colour.image));
    wrap.append(chip);
  });
  return wrap;
}

function buildDensityPill(current, onPick) {
  const wrap = document.createElement("div");
  wrap.className = "density-pill";
  wrap.title = "ความหนาแน่นของชิ้นนี้";
  for (const level of DENSITY_LEVELS) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = DENSITY_LABEL_TH[level];
    button.setAttribute("aria-pressed", String(level === current));
    button.addEventListener("click", () => onPick(level));
    wrap.append(button);
  }
  return wrap;
}

/* Swaps an accepted item's picture to another colour of the same product, in place (issue
 * #15) — position, size override and density are all on `element` itself and untouched.
 * Reuses /api/element/from-catalog, the same endpoint the original accept went through, so
 * the swap is a pre-cut file read (issue #13), never a live background removal. */
async function switchColour(element, newImage) {
  if (newImage === element.image) return;
  showError("");
  try {
    const result = await fetchElementFromCatalog(element.code, newImage);
    element.url = result.element_url;
    element.name = result.element;
    element.image = newImage;
    element.sizeMm = result.size_mm;
    element.price = result.price ?? null;  // same code, so the same price — kept in step
  } catch (err) {
    showError(err.message);
  }
  resetRun(); // also redraws, which reverts the select to element.image on failure
}

/* Only reset when the user changes an input — that is the moment the previous run stops being
 * the current one. The pipeline chip, the result and any count all belong to that run. */
function resetRun() {
  store.result = null;
  store.run = { requestId: null, quantities: null, counted: null };
  store.status = "idle";
  store.ui.stageView = "original";
  showError("");
  render();
}

/* The pre-generate estimate, in the confirm dialog: how many of this product fit on a tree
 * that size, from the catalogue millimetres. Not reused against the finished picture — see
 * the count button at the bottom of this file for why those are two different numbers.
 * Indexed against store.decorations since that is the order /api/prepare received them in. An
 * entry is null when that item has no catalogue size — suggest_quantity() has no fallback for
 * that case the way scale_sentence() does, so the item is skipped rather than invented. */
function renderQuantities(target, quantities) {
  target.innerHTML = "";
  let shown = false;
  if (quantities) {
    quantities.forEach((q, i) => {
      if (!q) return;
      const li = document.createElement("li");
      li.textContent = `${store.decorations[i].code}: ควรใช้ประมาณ ${q.low}–${q.high} ชิ้นบนต้นนี้`;
      target.append(li);
      shown = true;
    });
  }
  target.hidden = !shown;
}

function showTotals(totals) {
  $("generations").textContent = totals.generations;
  $("tokens").textContent = totals.total_tokens.toLocaleString();
}

async function refreshTotals() {
  try {
    showTotals(await call("/api/usage"));
  } catch (err) {
    showError(err.message);
  }
}

/* How many packs to pull off the shelf for a finished run (issue #25) — the number a shop can
 * actually order against, which a piece count is not when the product comes in boxes of ten.
 *
 * Only products sold by the pack appear here. A loose one has nothing to convert, and its
 * piece estimate stays off this panel for the reason given where the count button is set up:
 * it answers "how many fit on a tree this size", and the finished picture routinely does not
 * honour that scale. The pack figure is not a reading of the picture either, which is what
 * #stock-note says out loud. */
function renderStock(elements) {
  const list = $("result-stock");
  list.innerHTML = "";
  for (const element of elements || []) {
    if (!element.quantity || !element.packs) continue;
    const pieces = rangeText(element.quantity.low, element.quantity.high);
    const li = document.createElement("li");
    li.textContent = `${element.code}: ${packPhrase(element.packs)} — ประมาณ ${pieces} ชิ้น`;
    list.append(li);
  }
  const shown = list.children.length > 0;
  list.hidden = !shown;
  $("stock-note").hidden = !shown;
}

const ORIENTATION_TH = { portrait: "แนวตั้ง", landscape: "แนวนอน", square: "จัตุรัส" };

async function loadConfig() {
  const config = await call("/api/config");
  store.config = { sizes: config.sizes, densities: config.densities };
  store.limits.maxElements = config.max_elements;
  store.limits.promptMaxChars = config.prompt_mode_max_chars;
  store.output = { ratio: config.default_size, density: config.default_density };
  render();
}

$("size-select").addEventListener("change", () => { store.output.ratio = $("size-select").value; });
$("density-select").addEventListener("change", () => { store.output.density = $("density-select").value; });

/* ---- picking the output size from the photos actually given, not a fixed default ----
 * The size selector used to just sit on Product.md's 4:5 default until a user thought to
 * change it — which most never did, so a landscape room or a wide tree photo generated into
 * a portrait canvas regardless. This reads the real width/height of whatever is in the tree
 * and scene slots and moves the selector to whichever preset is the closest match, so
 * "what I picked" and "what came out" agree without the user having to know gpt-image-2's
 * five fixed ratios exist.
 *
 * The scene reference wins when both are present. It is what the final crop actually has to
 * live inside — the tree photo's own framing gets discarded anyway once a setting is
 * composited behind it (image_gen.REFERENCE_SCENE), so matching the tree's shape would aim
 * at a frame the result does not keep. */
function imageDimensions(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve({ width: img.naturalWidth, height: img.naturalHeight });
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("อ่านขนาดรูปไม่ได้"));
    };
    img.src = url;
  });
}

async function ratioOf(file) {
  try {
    const { width, height } = await imageDimensions(file);
    return width / height;
  } catch {
    return null; /* size auto-pick is a convenience; a photo the browser can't measure still uploads fine */
  }
}

function nearestSizeKey(ratio) {
  const presets = store.config.sizes;
  if (!presets.length || !ratio) return null;
  // compared in log space so a 2:1 landscape and a 1:2 portrait are equally "far" from
  // square — a plain numeric difference would treat every landscape preset as closer to
  // square than any portrait one just because their ratio values happen to be larger
  let best = null;
  let bestDiff = Infinity;
  for (const preset of presets) {
    const diff = Math.abs(Math.log(preset.width / preset.height) - Math.log(ratio));
    if (diff < bestDiff) {
      bestDiff = diff;
      best = preset.key;
    }
  }
  return best;
}

function refreshAutoSize() {
  // a scene reference wins outright — "auto" sends its exact ratio (fit_custom_size on the
  // backend), so there is no "nearest of five" step to run once one is set. Without a scene,
  // the tree photo's own ratio still snaps to the closest preset, same as before this option
  // existed. Either way the user can still override manually via the dropdown afterward.
  if (store.atmosphereRef && store.atmosphereRef.ratio) {
    store.output.ratio = "auto";
    return;
  }
  const key = nearestSizeKey(store.base && store.base.ratio);
  if (key) store.output.ratio = key;
}

/* ---- the base photo (tree, wall or door) ---- */

/* Codes are never typed on this page: they ride along with whatever the catalogue picker
 * hands over, and are shown burned onto the preview so they can still be read back.
 * Product.md 8.2 wanted them so the prompt could state real millimetres; a code typed from
 * memory out of ~1,300 was always a wrong order waiting to happen. Settings is where a code
 * gets entered by hand, against the catalogue row it belongs to. A new base starts its size
 * gate over from nothing, and an uploaded photo carries no code at all. */
async function setBase({ file, url, code = null, sizeMm = null, price = null }) {
  const ratio = await ratioOf(file);
  store.base = {
    type: store.backdrop, file, url, code,
    sizeMm: code ? sizeMm : null, manualMm: null,
    price: code ? price : null, typedPrice: null, ratio,
  };
  refreshAutoSize();
  resetRun();
}

function setBaseFromFile(file) {
  showError("");
  return setBase({ file, url: URL.createObjectURL(file) });
}

function clearBase() {
  store.base = null;
  resetRun();
}

function setBackdrop(type) {
  if (store.backdrop === type) return;
  // Auto's recipe and tones are per backdrop (issue #24): a tone chosen for a tree means nothing on a wall
  store.tone = null;
  store.auto.pick = null;
  store.auto.pickError = null;
  store.auto.exclude = [];
  setStore({ backdrop: type });
}

$("base-file").addEventListener("change", (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (file) setBaseFromFile(file);
});

/* ---- lightbox: a full-size look at a candidate's photo before deciding ----
 * A corner button, not a click on the card itself — .candidate.pickable's whole-card click
 * already means "use this one", so the preview needs its own target and has to stop the
 * click from reaching the card under it. identify.js carries an identical copy of this for
 * its own (non-pickable) match-result cards. */
function openLightbox(src, alt) {
  $("lightbox-image").src = src;
  $("lightbox-image").alt = alt;
  $("lightbox-dialog").showModal();
}

$("lightbox-close").addEventListener("click", () => $("lightbox-dialog").close());

function renameButton(item, label) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "candidate-rename";
  button.setAttribute("aria-label", "แก้ชื่อสี");
  button.textContent = "✎";
  button.addEventListener("click", async (event) => {
    event.stopPropagation();
    const typed = prompt("ชื่อสีนี้ (ภาษาไทย)", item.colour_name || "");
    if (!typed || !typed.trim()) return;
    try {
      const body = new FormData();
      body.append("image", item.image);
      body.append("name_th", typed.trim());
      await call(`/api/catalog/products/${encodeURIComponent(item.code)}/colour-name`, {
        method: "POST", body,
      });
      item.colour_name = typed.trim();
      label.textContent = item.colour_name;
    } catch (err) {
      alert(err.message);
    }
  });
  return button;
}

function expandButton(src, alt) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "candidate-expand";
  button.setAttribute("aria-label", "ดูรูปเต็ม");
  button.textContent = "⤢";
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    openLightbox(src, alt);
  });
  return button;
}

// Visible when browsing, never pickable (issue #17) — only a peek at the first supporting
// photo; the full set is managed from the settings page's find-and-correct screen.
function moreButton(item) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "candidate-more";
  button.textContent = `+${item.supporting.length} รูปเพิ่มเติม`;
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    openLightbox(catalogImageUrl(item.supporting[0]), item.code);
  });
  return button;
}

/* ---- catalogue picker: an alternate source for the same "element" slot ----
 * Skips the browser file upload entirely — the photo already lives on the server, so it
 * goes straight through the same rembg pipeline and lands in the same preview/accept flow.
 * Paged rather than all-at-once: the catalogue is ~1,250 products with a photo each, and a
 * grid that requests every one of them on open is a slideshow of spinners. */
const CATALOG_PAGE = 60;
let catalogTimer;
let catalogQuery = "";
let catalogCodesShown = 0;   // products consumed — what the next page's offset advances by
let catalogCardsShown = 0;   // cards on screen, larger when a product has several colours
let catalogPickerMode = "element";   // "element" (any category) or "tree" (locked to the
                                      // tree category) — the same dialog serves every caller
                                      // (panel 1, panel 2, prompt.js's chat chips) rather than
                                      // duplicating the whole grid/search/page machinery
let catalogPickerCallback = null;    // (code, image) => void — set by openCatalogPicker(),
                                      // called by catalogCard()'s click instead of a hardcoded
                                      // if/else, so a new caller needs no new branch here

function catalogCard(item) {
  const card = document.createElement("div");
  card.className = "candidate pickable";
  const photo = document.createElement("img");
  photo.src = catalogImageUrl(item.image);
  photo.alt = item.code;
  photo.loading = "lazy";
  const code = document.createElement("div");
  code.className = "code";
  code.textContent = item.size_raw ? `${item.code} — ${item.size_raw}` : item.code;
  card.append(photo, code);
  // the same code appears once per colour, so the card has to say which one it is
  if (item.colours > 1) {
    // Named once a shop has run/corrected the seeding pass (issue #14); falls back to a
    // plain position label for a colour nobody has named yet — never invented.
    const which = document.createElement("div");
    which.className = "why";
    which.textContent = colourLabel(item.colour_name, item.colour, item.colours);
    card.append(which);
    card.append(renameButton(item, which));
  }
  if (item.image) card.append(expandButton(catalogImageUrl(item.image), item.code));
  if (item.supporting && item.supporting.length) card.append(moreButton(item));
  // A tree pick closes the dialog itself and returns nothing worth reporting here. A
  // decoration pick (issue #28) does not — the dialog stays open for the next pick, so this
  // is the only place left to say what just happened: a string is an error or a "you're full"
  // refusal to show verbatim, `true` is a plain success, anything else is quietly ignored.
  card.addEventListener("click", async () => {
    const result = await catalogPickerCallback(item.code, item.image);
    if (typeof result === "string") $("catalog-count").textContent = result;
    else if (result === true) {
      $("catalog-count").textContent = `เพิ่ม ${item.code} แล้ว ✓`;
      renderCatalogPicked();
    }
  });
  return card;
}

function skeletonCard() {
  const card = document.createElement("div");
  card.className = "candidate candidate-skeleton";
  return card;
}

async function loadCatalogShops() {
  try {
    const { shops } = await call("/api/catalog/shops");
    const select = $("catalog-shop");
    for (const item of shops) {
      const option = document.createElement("option");
      option.value = item.key;
      option.textContent = `${item.label} (${item.count})`;
      select.append(option);
    }
  } catch {
    /* the filter is a convenience; browsing every shop together still works without it */
  }
}

/* Which backdrop the picker is filling for (issue #23). Only the decoration picker filters:
 * the tree picker is choosing the backdrop itself, so it browses the whole catalogue. */
function pickerBackdrop() {
  return catalogPickerMode === "element" ? store.backdrop : "";
}

/* The category list belongs to whichever shop is selected, so it is rebuilt whenever that
 * changes rather than fetched once. Counted across every shop it advertised stock the chosen
 * shop does not carry — MS Natural Design still offered ribbons (43), bells (25) and toppers
 * (15), all of them Bangkok Christmas products, and picking one gave an empty grid.
 * The current choice is kept when the new shop also has that category and falls back to
 * "every category" when it does not, so switching shop never leaves a filter selected that
 * matches nothing. */
async function loadCatalogCategories() {
  const select = $("catalog-category");
  const wanted = select.value;
  try {
    const shop = $("catalog-shop").value;
    const { categories } = await call(
      `/api/catalog/categories?book=${encodeURIComponent(shop)}` +
        `&backdrop=${encodeURIComponent(pickerBackdrop())}`
    );
    // everything after the "ทุกหมวด" option is the previous shop's list
    while (select.options.length > 1) select.remove(1);
    for (const item of categories) {
      const option = document.createElement("option");
      option.value = item.key;
      option.textContent = `${item.label} (${item.count})`;
      select.append(option);
    }
    select.value = categories.some((item) => item.key === wanted) ? wanted : "";
  } catch {
    /* the filter is a convenience; browsing everything still works without it */
  }
}

async function loadCatalogPage(restart) {
  const host = $("catalog-results");
  if (restart) {
    catalogCodesShown = 0;
    catalogCardsShown = 0;
    host.innerHTML = "";
    for (let i = 0; i < 10; i++) host.append(skeletonCard());
  }
  try {
    const { results, total, codes } = await call(
      `/api/catalog/search?q=${encodeURIComponent(catalogQuery)}` +
        `&category=${encodeURIComponent($("catalog-category").value)}` +
        `&book=${encodeURIComponent($("catalog-shop").value)}` +
        `&backdrop=${encodeURIComponent(pickerBackdrop())}` +
        `&limit=${CATALOG_PAGE}&offset=${catalogCodesShown}`
    );
    if (restart) host.innerHTML = "";
    for (const item of results) host.append(catalogCard(item));
    catalogCodesShown += codes;
    catalogCardsShown += results.length;
    const extra = catalogCardsShown > catalogCodesShown ? ` (${catalogCardsShown} รูป แยกสีแล้ว)` : "";
    $("catalog-count").textContent = total
      ? `แสดง ${catalogCodesShown} จาก ${total} ชิ้น${extra}`
      : "ไม่เจอสินค้าที่ตรงกับที่ค้น";
    $("catalog-more").hidden = catalogCodesShown >= total;
  } catch (err) {
    if (restart) host.innerHTML = "";
    $("catalog-count").textContent = err.message;
  }
}

/* Panel 1 opens the same dialog locked to the tree category; panel 2 opens it free. Always
 * reloads on open rather than reusing whatever the grid last showed — otherwise switching
 * from one panel's picker to the other's would show the wrong (stale-mode) results. The shop
 * filter is never locked by mode — both shops sell trees, so panel 1 still needs to choose
 * between them, just within the tree category. */
/* The strip of what has been picked so far, drawn inside the dialog (issue #31): the accepted
 * list itself sits on the page behind the modal, so without this the only sign a pick landed
 * is one line of text that the next pick overwrites.
 *
 * Reads the caller's own list every time rather than counting picks as they happen — the two
 * decoration pickers keep separate lists (store.decorations, and Prompt mode's before it shared them), and a
 * tally kept here would be a third copy free to disagree with both. `catalogPickerPicked` is
 * whichever provider the current caller handed openCatalogPicker; the tree picker hands none,
 * which is also how the strip knows to stay hidden for a slot that holds one tree. */
let catalogPickerPicked = null;   // () => [{code, url}] | null

function renderCatalogPicked() {
  const host = $("catalog-picked");
  host.innerHTML = "";
  const picked = catalogPickerPicked ? catalogPickerPicked() : [];
  host.hidden = !picked.length;
  if (!picked.length) return;

  const label = document.createElement("span");
  label.className = "hint";
  label.textContent = `เลือกแล้ว ${picked.length} จาก ${store.limits.maxElements} ชิ้น`;
  host.append(label);

  const strip = document.createElement("div");
  strip.className = "picker-picked-strip";
  for (const item of picked) {
    // same thumbnail vocabulary the accepted list uses — these are the same transparent
    // cut-outs, so they need the same checker backing to read against a light dialog
    const wrap = document.createElement("div");
    wrap.className = "thumb-wrap";
    const img = document.createElement("img");
    img.className = "thumb-sm checker";
    img.src = item.url;
    img.alt = item.code || "ของตกแต่งที่เลือกไว้";
    wrap.append(img);
    if (item.code) {
      const badge = document.createElement("span");
      badge.className = "thumb-code";
      badge.textContent = item.code;
      wrap.append(badge);
    }
    strip.append(wrap);
  }
  host.append(strip);
}

async function openCatalogPicker(mode, onPick, listPicked = null) {
  catalogPickerMode = mode;
  catalogPickerCallback = onPick;
  catalogPickerPicked = listPicked;
  renderCatalogPicked();
  const categorySelect = $("catalog-category");
  const shopSelect = $("catalog-shop");
  // shops first: the category list is scoped to the selected shop, so it cannot be built
  // until the shop select holds a real value. Both awaited — firing and moving on left the
  // "tree" lock unset on whichever picker opened first.
  if (shopSelect.options.length <= 1) await loadCatalogShops();
  await loadCatalogCategories();
  categorySelect.disabled = mode === "tree";
  categorySelect.value = mode === "tree" ? "tree" : "";
  $("catalog-dialog").showModal();
  loadCatalogPage(true);
}

$("catalog-shop").addEventListener("change", async () => {
  // categories first: the grid must not be reloaded against a filter the new shop has no
  // stock for, which is exactly what the old order left on screen
  await loadCatalogCategories();
  if (catalogPickerMode === "tree") $("catalog-category").value = "tree";
  loadCatalogPage(true);
});

$("catalog-category").addEventListener("change", () => loadCatalogPage(true));

$("catalog-close").addEventListener("click", () => $("catalog-dialog").close());
$("catalog-more").addEventListener("click", () => loadCatalogPage(false));

$("catalog-search").addEventListener("input", () => {
  clearTimeout(catalogTimer);
  catalogQuery = $("catalog-search").value.trim();
  catalogTimer = setTimeout(() => loadCatalogPage(true), 200);
});

/* Picking a decoration runs the same background removal an upload does, and the first one
 * after launch pays for loading the model: measured 10s on a warm dev box and 68s on a cold
 * installed copy. Without this the dialog just sat there looking frozen, and every further
 * click started another cut — several rembg calls fighting over one session, which is what
 * turned a slow pick into a stuck one. Same treatment the upload button already gets. */
let catalogBusy = false;

function setCatalogBusy(busy, message) {
  catalogBusy = busy;
  $("catalog-results").classList.toggle("is-busy", busy);
  if (busy) $("catalog-count").textContent = message;
}

/* The one request every catalogue-element pick makes, whether it is the first pick
 * (addElementFromCatalog) or a later colour switch (switchColour, issue #15) — same code+image pair,
 * same precut-aware endpoint (issue #13: a file read, never a live background removal). */
async function fetchElementFromCatalog(code, image) {
  const body = new FormData();
  body.append("code", code);
  if (image) body.append("image", image);
  return call("/api/element/from-catalog", { method: "POST", body });
}

/* A code's other colours (issue #15), for the accepted-item switcher — fetched once at
 * accept/add time rather than on every render, which would ask the same question dozens of
 * times over a session. A product with only one colour comes back with exactly one entry,
 * which is also the "offer no switcher" signal downstream, so `null` (not `[]`) is what
 * means "nothing to switch between". Shared by the upload path's accept-btn and the
 * catalogue path's addElementFromCatalog — same question, asked the same way either time. */
async function lookupColours(code) {
  if (!code) return null;
  try {
    const found = await call(`/api/catalog/products/${encodeURIComponent(code)}/colours`);
    return found.colours.length > 1 ? found.colours : null;
  } catch {
    return null; // the switcher is a convenience; a decoration must still work without it
  }
}

/* ---- decorations ---- */

/* A catalogue pick is a known-good pre-cut product photo, never a live rembg cut that might
 * come out wrong — so unlike an uploaded photo it goes straight into the list, already
 * "ready". The dialog stays open afterwards (issue #28), so picking five decorations is five
 * clicks in the one dialog, not five open/pick/close/reopen cycles.
 *
 * The first cut after launch pays for loading the model: measured 10s on a warm dev box and
 * 68s on a cold installed copy, so the grid dims and stops taking clicks while one runs
 * (setCatalogBusy) — several rembg calls fighting over one session is what turned a slow pick
 * into a stuck one.
 *
 * Returns what catalogCard() should tell the shop: a string to show verbatim (the cap was
 * already full, or the pick failed), or `true` for a plain success. */
async function addDecorationFromCatalog(code, image) {
  if (catalogBusy) return undefined;
  const max = store.limits.maxElements;
  if (store.decorations.length >= max) {
    return `ใส่ได้ถึง ${max} ชิ้น — เอาออกสักชิ้นถ้าจะเพิ่ม`;
  }
  setCatalogBusy(true, "กำลังตัดพื้นหลัง… ครั้งแรกหลังเปิดโปรแกรมจะนานหน่อย");
  try {
    const result = await fetchElementFromCatalog(code, image);
    store.decorations.push({
      name: result.element, url: result.element_url, code, image: image || null,
      colours: await lookupColours(code),
      sizeMm: result.size_mm, manualMm: null, price: result.price ?? null, typedPrice: null,
      density: "normal", status: "ready",
    });
    resetRun();
    return true;
  } catch (err) {
    // the dialog is still open (that's the whole point of this function), so the usual
    // showError() would land in a box the open <dialog> covers — #catalog-count is what is
    // actually visible right now. Still calls showError too: closing the dialog without
    // having noticed the last pick failed should not read as a quiet, working app.
    showError(err.message);
    return err.message;
  } finally {
    setCatalogBusy(false);
  }
}

/* An uploaded photo goes through the same background removal a catalogue pick has already had
 * (NonGoals: never skip it). With "ตัดพื้นหลังอัตโนมัติ" ticked that happens straight away, one
 * photo at a time; unticked, the row waits with its own "ตัดพื้นหลัง" button. Either way a bad cut
 * is a dead end the user can back out of by removing the row (AC-2). */
async function cutDecoration(item) {
  item.status = "cutting";
  render();
  try {
    const body = new FormData();
    body.append("files", item.file);
    const result = await call("/api/remove-bg", { method: "POST", body });
    item.name = result.element;
    item.url = result.element_url;
    item.file = null;
    item.status = "ready";
  } catch (err) {
    // rembg failed. Nothing continues on its own — the user removes the row and re-uploads.
    item.status = "failed";
    item.error = err.message;
    showError(err.message);
  }
  render();
}

async function addDecorationFiles(files) {
  const room = store.limits.maxElements - store.decorations.length;
  const added = [];
  for (const file of files.slice(0, Math.max(room, 0))) {
    const item = {
      name: null, url: URL.createObjectURL(file), file, code: null, image: null, colours: null,
      sizeMm: null, manualMm: null, price: null, typedPrice: null, density: "normal",
      status: store.ui.autoCut ? "cutting" : "pending",
    };
    store.decorations.push(item);
    added.push(item);
  }
  if (!added.length) return;
  resetRun();
  if (store.ui.autoCut) for (const item of added) await cutDecoration(item);
}

function removeDecoration(index) {
  store.decorations.splice(index, 1);
  resetRun();
}

$("element-file").addEventListener("change", (event) => {
  const files = [...event.target.files];
  event.target.value = "";
  if (files.length) addDecorationFiles(files);
});

/* ---- the optional scene/ambience reference ----
 * Uploaded on its own endpoint rather than with the tree, because it is not
 * background-removed: its background is the only thing being taken from it. Independent of
 * the find-from-photo page (identify.html/identify.js) — this one only ever feeds the
 * background of the generated result, never the catalogue search. */
async function setAtmosphereFromFile(file) {
  showError("");
  try {
    const body = new FormData();
    body.append("files", file);
    const result = await call("/api/reference", { method: "POST", body });
    store.atmosphereRef = { name: result.reference, url: result.reference_url, ratio: await ratioOf(file) };
    store.ui.atmosphereOpen = true;
    store.ui.sceneSamples = false;
    refreshAutoSize();
  } catch (err) {
    showError(err.message);
  }
  resetRun();
}

function clearAtmosphere() {
  store.atmosphereRef = null;
  refreshAutoSize(); // falls back to the tree photo's own ratio, if any
  resetRun();
}

$("atmosphere-file").addEventListener("change", (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (file) setAtmosphereFromFile(file);
});

/* ---- sample pictures ----
 * A shop trying the app for the first time has no bare-tree photo and no room photo to hand,
 * which is two dead ends before it can generate anything. These are committed under
 * frontend/samples/ and served by the existing /static mount, so there is no endpoint here —
 * each one is fetched as a blob and then goes through exactly the path a real upload takes.
 * Nothing downstream can tell a sample from something the user chose, which is the point.
 *
 * A sample tree carries no catalogue code, the same as any other photo the user supplies. */
const SAMPLE_TREES = [
  { file: "tree-slim-green.jpg", label: "ต้นทรงสูงเรียว" },
  { file: "tree-full-green.jpg", label: "ต้นทรงเต็ม" },
  { file: "tree-tall-green.jpg", label: "ต้นทรงสูง" },
];

const SAMPLE_SCENES = [
  { file: "living-fireplace-bright.jpg", label: "ห้องโล่ง เตาผิง แสงกลางวัน" },
  { file: "living-fireplace-minimal.jpg", label: "ห้องโล่ง เตาฟืน" },
  { file: "living-vintage-warm.jpg", label: "ห้องวินเทจ แสงอุ่น" },
  { file: "empty-room-windows.jpg", label: "ห้องเปล่า หน้าต่างใหญ่" },
  { file: "living-corner-window.jpg", label: "มุมโซฟาริมหน้าต่าง" },
  { file: "living-plants-wood.jpg", label: "ห้องโทนอุ่น ต้นไม้" },
];

async function fetchSampleFile(url, type = "image/jpeg") {
  const blob = await (await fetch(url)).blob();
  return new File([blob], url.split("/").pop(), { type });
}

async function useSampleTree(url) {
  showError("");
  try {
    store.ui.samples = false;
    await setBase({ file: await fetchSampleFile(url), url });
  } catch (err) {
    showError(err.message);
  }
}

async function useSampleScene(url) {
  try {
    await setAtmosphereFromFile(await fetchSampleFile(url));
  } catch (err) {
    showError(err.message);
  }
}

/* Same idea as a decoration pick, but for the base slot — no background removal (a tree keeps
 * its own photographed background), so it needs a real File the same way an upload produces
 * one, not just a stored server filename. */
async function useTreeFromCatalog(code, image) {
  if (catalogBusy) return;
  showError("");
  setCatalogBusy(true, "กำลังโหลดรูปต้น…");
  try {
    const body = new FormData();
    body.append("code", code);
    if (image) body.append("image", image);
    const result = await call("/api/tree/from-catalog", { method: "POST", body });
    const blob = await (await fetch(result.tree_url)).blob();
    await setBase({
      file: new File([blob], result.tree, { type: "image/png" }),
      url: result.tree_url, code, sizeMm: result.size_mm, price: result.price ?? null,
    });
    $("catalog-dialog").close();
  } catch (err) {
    $("catalog-dialog").close();
    showError(err.message);
  } finally {
    setCatalogBusy(false);
  }
}

/* ---- prepare, confirm, generate ---- */

/* The whole /api/prepare form for what is currently set, and nothing else — every field the
 * server ever receives about a run comes from here (/api/generate has no body at all). `exact`
 * is exactScaleReady(): the all-codes-or-none gate. Kept apart from the click handler so a dry
 * run (?dryrun=1) can read exactly what a real run would send.
 *
 * Custom and Auto share one shape. Prompt mode sends the same photos with its typed text in
 * place of a density (backend/main.py's /api/generate substitutes it into {density}, after the
 * template's own hard preservation rules, never before them). */
function buildGenerateRequest(exact) {
  return store.mode === "prompt" ? buildPromptRequest(exact) : buildCustomRequest(exact);
}

function appendSize(body) {
  body.append("size", store.output.ratio);
  if (store.output.ratio === "auto") {
    const scene = store.atmosphereRef && store.atmosphereRef.ratio;
    body.append("scene_ratio", String(scene || (store.base && store.base.ratio) || ""));
  }
}

function buildCustomRequest(exact) {
  const body = new FormData();
  body.append("files", store.base.file);
  body.append("backdrop", store.backdrop);
  appendSize(body);
  body.append("density", store.output.density);
  body.append("tree_code", exact ? store.base.code : "");
  body.append("tree_manual_mm", store.base.manualMm != null ? String(store.base.manualMm) : "");
  if (store.atmosphereRef) body.append("reference", store.atmosphereRef.name);
  for (const element of store.decorations) {
    body.append("element", element.name);
    body.append("element_code", exact ? element.code : "");
    // Travels with the code, never without it (issue #16) — a colour is only meaningful
    // paired with the product it names one photo of (ADR-0002), same "all codes or none"
    // gate `exact` already applies to element_code above.
    body.append("element_image", exact ? (element.image || "") : "");
    body.append("element_manual_mm", element.manualMm != null ? String(element.manualMm) : "");
    body.append("element_density", element.density || "");
  }
  return body;
}

function buildPromptRequest(exact) {
  const body = new FormData();
  body.append("files", store.base.file);
  if (store.backdrop !== "tree") body.append("backdrop", store.backdrop);
  appendSize(body);
  body.append("density", "normal"); // irrelevant once custom_prompt wins server-side
  body.append("tree_code", exact ? store.base.code : "");
  body.append("tree_manual_mm", store.base.manualMm != null ? String(store.base.manualMm) : "");
  body.append("custom_prompt", store.prompt.trim());
  if (store.atmosphereRef) body.append("reference", store.atmosphereRef.name);
  for (const element of store.decorations) {
    body.append("element", element.name);
    body.append("element_code", exact ? element.code : "");
    body.append("element_manual_mm", element.manualMm != null ? String(element.manualMm) : "");
    body.append("element_density", "normal");
  }
  return body;
}

$("generate-btn").addEventListener("click", async () => {
  setStore({ busy: true });
  showError("");

  // all the codes or none: a partial set cannot produce a ratio and the server refuses it,
  // and it is no longer something the user could complete by hand (see exactScaleReady)
  const exact = exactScaleReady();
  const droppedCodes = !exact
    && (Boolean(store.base.code) || store.decorations.some((element) => element.code));

  try {
    const body = buildGenerateRequest(exact);
    if (dryRunEnabled()) {
      dryRunReport(store.mode, body);
      setStore({ busy: false });
      return;
    }

    const prepared = await call("/api/prepare", { method: "POST", body });
    store.run.requestId = prepared.request_id;
    store.status = "pending";
    const many = prepared.element_count > 1
      ? `ของตกแต่ง ${prepared.element_count} ชิ้นผสมกัน`
      : `ของตกแต่ง 1 ชิ้น`;
    $("confirm-body").textContent =
      `สร้างภาพ ${prepared.width} × ${prepared.height} หนึ่งภาพ พร้อม${many} · ` +
      `เสียเงินเฉพาะตอนที่ได้ภาพกลับมา · ` +
      (prepared.reference_url
        ? `ต้นจะย้ายไปอยู่ในสถานที่ตามรูปอ้างอิง · `
        : `ต้นจะอยู่บนพื้นหลังเดิม · `) +
      (prepared.exact_scale
        ? `ขนาดตรงตามแคตตาล็อกทุกชิ้น`
        : prepared.missing_sizes.length
          ? `บางชิ้นไม่มีขนาดในแคตตาล็อก — ดูด้านล่าง`
          : droppedCodes
            ? `มีบางชิ้นที่ไม่ได้เลือกจาก catalogue ขนาดจึงไม่ตรงของจริง`
            : `ไม่ได้เลือกจาก catalogue ขนาดจึงไม่ตรงของจริง`);

    // Prompt mode: say back what will be asked for, since it replaces the density choice
    const text = store.prompt.trim();
    const preview = $("confirm-prompt-preview");
    preview.textContent = text ? `“${text}”` : "";
    preview.hidden = store.mode !== "prompt" || !text;

    const missingBox = $("confirm-missing-sizes");
    missingBox.textContent = prepared.missing_sizes.length
      ? `แคตตาล็อกไม่มีขนาดของ: ${prepared.missing_sizes.join(", ")} — ขนาดชิ้นนี้จะไม่ตรงของจริง`
      : "";
    missingBox.hidden = !prepared.missing_sizes.length;

    store.run.quantities = prepared.quantities || null;
    renderQuantities($("confirm-quantities"), store.run.quantities);

    $("confirm-btn").disabled = false;
    render();
    $("confirm-dialog").showModal();
  } catch (err) {
    showError(err.message);
    setStore({ busy: false });
  }
});

$("cancel-btn").addEventListener("click", () => {
  $("confirm-dialog").close();
  store.run.requestId = null;
  store.status = "idle";
  setStore({ busy: false });
});

$("confirm-btn").addEventListener("click", async () => {
  // first line of defence against a double-click; the server's claim() is the second
  $("confirm-btn").disabled = true;
  $("confirm-dialog").close();
  store.ui.stageView = "result"; // the spinner and then the picture appear on the stage
  setStore({ status: "calling_api" });

  try {
    const requestId = store.run.requestId;
    const result = await call(`/api/generate/${requestId}`, { method: "POST" });
    showTotals(result.totals);
    // the pre-generate suggestion is not shown against the finished picture: it answers "how
    // many fit on a tree this size" from the catalogue millimetres, and the picture routinely
    // does not honour that scale. Counting the picture itself is the button on the stage.
    setStore({ result, status: "api_success" });

    // tell the server the browser really got it, so a row left at api_success is a genuine
    // "paid for, never seen" case and not just a page that forgot to say so (Spec.md 7)
    await call(`/api/delivered/${requestId}`, { method: "POST" }).catch(() => {});
    setStore({ status: "delivered" });
  } catch (err) {
    showError(err.message);
    setStore({ status: "api_failed" });
  } finally {
    setStore({ busy: false });
    refreshTotals();
  }
});

/* ---- how many are actually in the finished picture ----
 * A separate, billed vision call, so it is a button rather than something that runs itself
 * after every generation — same rule the catalogue search follows. What it answers is the
 * question the shop quotes from: the size-based suggestion says how many would fit on a tree
 * that size, the picture regularly shows a different number, and the customer is looking at
 * the picture. */
/* Shared by a fresh count-btn click and by resumeFromHistory's replay of a persisted count
 * (request_log.set_counted, backend/main.py) — same list, same store.run.counted, so a result
 * read back from history looks identical to one just counted live. `note` is omitted on replay
 * (nothing new was just billed, so the "billed a little more" hint would be wrong). */
function applyCountedItems(items, note) {
  store.run.counted = { items, note: note || "" };
  render();
}

$("count-btn").addEventListener("click", async () => {
  if (!store.run.requestId) return;
  const btn = $("count-btn");
  btn.disabled = true;
  btn.textContent = "กำลังนับ…";
  showError("");

  try {
    const counted = await call(`/api/count/${store.run.requestId}`, { method: "POST" });
    applyCountedItems(counted.items, counted.note);
  } catch (err) {
    showError(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "นับของในรูปนี้";
  }
});

/* ---- custom-styled dropdown, layered over a real <select> ----
 * The select stays in the DOM and keeps doing the actual work — value, disabled, options,
 * dispatched change events — every call site above (loadConfig, loadCatalogShops,
 * loadCatalogCategories, openCatalogPicker, ...) keeps using it exactly as before. This only
 * adds a styled trigger + popup on top and keeps the two in sync, so a native <select>'s own
 * popup — which CSS can only ever touch for color and font, never radius or shadow — never
 * has to ship as the visible UI.
 */
function enhanceSelect(select) {
  const wrap = document.createElement("div");
  wrap.className = "select-wrap";
  if (select.id) wrap.dataset.for = select.id;
  select.before(wrap);

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = `${select.className} select-trigger`;
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", "false");

  const popup = document.createElement("div");
  popup.className = "select-popup";
  popup.setAttribute("role", "listbox");
  popup.hidden = true;

  wrap.append(trigger, popup, select);
  select.classList.add("select-native");
  select.tabIndex = -1;
  select.setAttribute("aria-hidden", "true");

  function syncTrigger() {
    const opt = select.options[select.selectedIndex];
    trigger.textContent = opt ? opt.textContent : "";
    trigger.disabled = select.disabled;
  }

  function closePopup() {
    popup.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
  }

  function focusRow(index) {
    const rows = popup.children;
    if (!rows.length) return;
    rows[(index + rows.length) % rows.length].focus();
  }

  function openPopup() {
    if (select.disabled) return;
    popup.innerHTML = "";
    [...select.options].forEach((opt, i) => {
      const row = document.createElement("div");
      row.className = "select-option" + (i === select.selectedIndex ? " modal-item" : "");
      row.textContent = opt.textContent;
      row.setAttribute("role", "option");
      row.setAttribute("aria-selected", i === select.selectedIndex ? "true" : "false");
      row.tabIndex = 0;
      const choose = () => {
        if (select.value === opt.value) { closePopup(); trigger.focus(); return; }
        select.value = opt.value;
        // Setting .value from script never fires 'change' on its own — without this the shop
        // and category filters silently do nothing, because loadCatalogPage is bound to that
        // event. A native <select> fires it when the user picks, so this popup must too.
        select.dispatchEvent(new Event("change", { bubbles: true }));
        closePopup();
        trigger.focus();
      };
      row.addEventListener("click", choose);
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(); }
        else if (event.key === "ArrowDown") { event.preventDefault(); focusRow(i + 1); }
        else if (event.key === "ArrowUp") { event.preventDefault(); focusRow(i - 1); }
        else if (event.key === "Escape") { closePopup(); trigger.focus(); }
      });
      popup.append(row);
    });
    popup.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    focusRow(Math.max(select.selectedIndex, 0));
  }

  trigger.addEventListener("click", () => (popup.hidden ? openPopup() : closePopup()));
  trigger.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); openPopup(); }
    else if (event.key === "Escape") closePopup();
  });
  // Tabbing out of the popup would otherwise leave it open behind whatever got focus next.
  // The timeout is needed because focusout fires before the new activeElement settles.
  wrap.addEventListener("focusout", () => {
    setTimeout(() => { if (!wrap.contains(document.activeElement)) closePopup(); }, 0);
  });
  document.addEventListener("click", (event) => {
    if (!wrap.contains(event.target)) closePopup();
  });

  // select.value and .disabled keep working exactly as every call site above already uses
  // them (including ones that set .value without dispatching change) — this only appends a
  // trigger-sync step after whichever native setter runs.
  for (const prop of ["value", "disabled"]) {
    const { get, set } = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, prop);
    Object.defineProperty(select, prop, {
      get,
      set(v) { set.call(select, v); syncTrigger(); },
    });
  }

  // options are populated after the fact (loadConfig, loadCatalogShops, loadCatalogCategories)
  new MutationObserver(syncTrigger).observe(select, { childList: true });
  syncTrigger();
}

document.querySelectorAll("select.input").forEach(enhanceSelect);

loadConfig().catch((err) => showError(err.message));
refreshTotals();

/* ---- mode switch — the three tabs in the top bar. Only `mode` changes: the base photo,
 * decorations, atmosphere reference and output settings all live in the store, so they are
 * exactly where they were when the tab is switched back. Reuses the sidebar nav's
 * .row/.row.active pattern for "which is active": Generate is the one control allowed the
 * primary-button colour on this page (test_ui_design_system.py rule 4), and a mode tab is
 * navigation, not that. */
async function setMode(mode) {
  showError("");
  setStore({ mode });
  if (mode === "auto") {
    try {
      await loadAutoConfig();
    } catch (err) {
      store.auto.pickError = err.message;
    }
    render();
  }
}
$("mode-btn-custom").addEventListener("click", () => setMode("custom"));
$("mode-btn-prompt").addEventListener("click", () => setMode("prompt"));
$("mode-btn-auto").addEventListener("click", () => setMode("auto"));

$("stage-tab-original").addEventListener("click", () => setStore({ ui: { ...store.ui, stageView: "original" } }));
$("stage-tab-result").addEventListener("click", () => setStore({ ui: { ...store.ui, stageView: "result" } }));
$("auto-refine-link").addEventListener("click", (event) => {
  event.preventDefault();
  setMode("custom"); // the pick is already in store.decorations — this is only a change of view
});

/* ---- "จัดการต่อ" from the history page (history.js's own link) ----
 * /?request_id=<id> pre-fills the base and decorations from a past request so it can be counted
 * (again, or for the first time) or re-checked for price without redoing the pick from scratch.
 * Read-only against the server (GET /api/request/{id}) — nothing here is a new request until
 * Generate is pressed again, which needs a real tree File the same as any other run, hence
 * re-fetching it as a blob rather than only pointing an <img> at the stored URL. */
function fileNameFrom(url) {
  return url ? url.split("/").pop() : null;
}

async function resumeFromHistory(requestId) {
  let row;
  try {
    row = await call(`/api/request/${requestId}`);
  } catch (err) {
    showError(err.message);
    return;
  }
  if (!row.output_url) {
    showError("request นี้ยังไม่มีภาพผลลัพธ์ให้จัดการต่อ");
    return;
  }

  const base = {
    type: store.backdrop, file: null, url: row.tree_url, code: row.tree_code || null,
    sizeMm: row.tree_size_mm, manualMm: row.tree_manual_mm, price: null, typedPrice: null, ratio: null,
  };
  try {
    const blob = await (await fetch(row.tree_url)).blob();
    base.file = new File([blob], fileNameFrom(row.tree_url), { type: "image/png" });
    base.ratio = await ratioOf(base.file);
  } catch {
    // Generate needs a real tree file; viewing/counting/pricing this request does not, so a
    // failed re-fetch here still leaves the rest of the resume usable.
  }
  store.base = base;
  refreshAutoSize();

  store.decorations = row.elements.map((e) => ({
    name: fileNameFrom(e.url),
    url: e.url,
    code: e.code,
    image: null,
    colours: null, // the colour switcher is a bonus of picking fresh; skip it on resume
    sizeMm: e.size_mm,
    manualMm: e.manual_mm,
    price: null,
    typedPrice: null,
    density: e.density || row.density || "normal",
    status: "ready",
  }));

  store.run = { requestId: row.request_id, quantities: null, counted: null };
  store.result = {
    request_id: row.request_id, output_url: row.output_url, size: row.size, usage: row.usage, resumed: true,
  };
  store.status = row.status;
  store.ui.stageView = "result";
  // request_log.set_counted persisted the last count for this request (backend/main.py) — a
  // resume replays it here for free instead of the count staying empty until someone pays to
  // count the same picture again.
  if (row.counted_items) store.run.counted = { items: row.counted_items, note: "" };
  setStore({ mode: "custom" });
}

const resumeId = new URLSearchParams(location.search).get("request_id");
if (resumeId) {
  resumeFromHistory(resumeId);
  // drop the query param so a later refresh replays the current on-screen state, not a
  // second fetch of the same request
  history.replaceState(null, "", location.pathname);
}
