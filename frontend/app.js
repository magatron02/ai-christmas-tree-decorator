/* Front end for the decorate page.
 *
 * Two things here are requirements rather than polish:
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

// Pre-fetch fallback only — renderElements() runs before loadConfig()'s await resolves.
// loadConfig() overwrites this with the real backend.config.MAX_ELEMENTS once it lands, so
// the two never have to be kept in sync by hand.
let MAX_ELEMENTS = 5;

const state = {
  treeFile: null,
  treeCode: null, // set only by the catalogue picker — an uploaded photo has no code
  treeSizeMm: null, // the tree code's catalogue size, or null if it has none (blocking gate)
  treeManualMm: null, // person-typed override when treeSizeMm is null
  treePrice: null, // the tree code's price, null = the book never printed one (issue #27)
  treeTypedPrice: null, // one typed into that offer and saved — shown back, never a gate
  // {name, url, code, image, colours, sizeMm, manualMm, price, density} — one entry per accepted
  // cut-out, up to MAX_ELEMENTS. sizeMm is the code's catalogue size (null = none, blocking
  // gate); manualMm is a person-typed override; price is the code's price (null = unpriced,
  // an offer to fill it in, never a gate) and typedPrice one filled into that offer;
  // density is a DENSITY_PRESETS key, per item.
  // image is the catalogue colour photo this cutout came from (null for an uploaded photo);
  // colours is that product's other colours (issue #15), fetched once at accept time — null
  // unless the product actually has more than one, which is also the "offer a switcher" flag.
  elements: [],
  sceneReference: null, // stored filename of the optional scene/ambience photo (used at generate time)
  requestId: null,
  busy: false,
  quantities: null, // prepared.quantities from the last /api/prepare, indexed like state.elements
  treeRatio: null, // width/height of whatever photo is in the tree slot right now
  sceneRatio: null, // width/height of the scene reference, when one is set
};

// A code-bearing item (tree or element) whose catalogue row has no size, and that has not
// been given a manual one yet — the thing the blocking gate exists to stop. NonGoals.md 8:
// the app must not guess this number, so Generate simply cannot be pressed until it is filled.
function needsManualSize(code, sizeMm, manualMm) {
  return Boolean(code) && sizeMm == null && manualMm == null;
}

function anyManualSizeMissing() {
  return needsManualSize(state.treeCode, state.treeSizeMm, state.treeManualMm)
    || state.elements.some((e) => needsManualSize(e.code, e.sizeMm, e.manualMm));
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
  return Boolean(state.treeCode) && state.elements.length > 0
    && state.elements.every((element) => element.code);
}

function refreshGenerateButton() {
  $("generate-btn").disabled =
    !(state.treeFile && state.elements.length) || state.busy || anyManualSizeMissing();
}

const DENSITY_LEVELS = ["light", "normal", "full"];
const DENSITY_LABEL_TH = { light: "โปร่ง", normal: "ปกติ", full: "แน่น" };

/* The markup both inline rows below share: a line of explanation, then a number field with its
 * unit. Only what they have in common lives here — each keeps its own wording, its own reason
 * for being hidden, and its own idea of when the typed value counts. */
function buildInlineRow({ warnText, warnClass, unit, min, placeholder, value }) {
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
  const unitLabel = document.createElement("span");
  unitLabel.className = "unit";
  unitLabel.textContent = unit;
  const field = document.createElement("div");
  field.className = "size-input-field";
  field.append(input, unitLabel);
  row.append(warn, field);
  return { row, input, warn };
}

/* The blocking size-input row + density pill shared by the tree slot and every accepted
 * element — one small builder so the two call sites (renderTreeSizeGate, renderElements)
 * agree on markup and behaviour instead of drifting apart. */
function buildSizeRow(sizeMm, manualMm, onInput) {
  if (sizeMm != null) {
    const hidden = document.createElement("div");
    hidden.className = "size-input-row";
    hidden.hidden = true;
    return hidden;
  }
  const { row, input, warn } = buildInlineRow({
    warnText: manualMm != null
      ? `✓ ใช้ ${manualMm} มม. ในการคำนวณสัดส่วน`
      : "ระบบจะไม่เดาขนาดให้ — ใส่ขนาดจริงก่อนสร้างภาพ",
    warnClass: manualMm != null ? "size-ok-text" : "size-warn-text",
    unit: "มม.", min: "1", placeholder: "เช่น 150", value: manualMm,
  });
  // `onInput` only updates state + Generate's disabled flag, both of which read state
  // directly and need no DOM of their own — never a re-render of the list this row lives in,
  // which would tear out and rebuild this very input mid-keystroke. Reported live: typing
  // "100" only ever registered the "1", because every keystroke's re-render handed focus to a
  // brand-new node the browser had never actually focused. The confirmation text below still
  // catches up, just on `change` (blur/Enter) rather than every keystroke, updated in place.
  input.addEventListener("input", () => onInput(input.value));
  input.addEventListener("change", () => {
    const parsed = Number(input.value);
    const value = input.value && parsed > 0 ? parsed : null;
    warn.className = value != null ? "size-ok-text" : "size-warn-text";
    warn.textContent = value != null
      ? `✓ ใช้ ${value} มม. ในการคำนวณสัดส่วน`
      : "ระบบจะไม่เดาขนาดให้ — ใส่ขนาดจริงก่อนสร้างภาพ";
  });
  return row;
}

/* The same inline treatment as the size row above, for a picked product the book never priced
 * (issue #27) — the shop notices the gap here, mid-pick, and can close it without leaving for
 * the pricing queue. Deliberately NOT a gate: a price has never been needed to make a picture
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

/* One write path for a price however it was typed: the pricing queue's own endpoint, which is
 * where this has always been stored (issue #27). Returns the price the server parsed, so the
 * panel shows what was actually saved rather than what was typed at it. */
async function savePrice(code, value) {
  const body = new FormData();
  body.append("price", value);
  const saved = await call(`/api/catalog/pricing-queue/${encodeURIComponent(code)}/price`, {
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

/* A dropdown of a decoration's other colours, by name (issue #15) — only ever built for an
 * item whose `colours` came back with more than one entry (state.elements' own "offer a
 * switcher" rule), so callers never have to check that here too. */
function buildColourSelect(colours, current, onPick) {
  const select = document.createElement("select");
  select.className = "input";
  colours.forEach((colour, index) => {
    const option = document.createElement("option");
    option.value = colour.image;
    option.textContent = colourLabel(colour.name, index + 1, colours.length);
    option.selected = colour.image === current;
    select.append(option);
  });
  select.addEventListener("change", () => onPick(select.value));
  return select;
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

/* Panel 1's own blocking gate — same rule as an accepted element, for the tree slot. Only
 * ever shown when the tree came from the catalogue (an uploaded photo has no code and no
 * catalogue size question to ask). */
function renderTreeSizeGate() {
  const host = $("tree-size-gate");
  host.innerHTML = "";
  host.hidden = !state.treeCode;
  if (!state.treeCode) return;
  host.append(buildSizeRow(state.treeSizeMm, state.treeManualMm, (value) => {
    const parsed = Number(value);
    state.treeManualMm = value && parsed > 0 ? parsed : null;
    refreshGenerateButton();
  }));
  host.append(buildPriceRow(state.treeCode, state.treePrice, state.treeTypedPrice, async (value) => {
    try {
      state.treeTypedPrice = await savePrice(state.treeCode, value);
      renderTreeSizeGate();
    } catch (err) {
      showError(err.message);
    }
  }));
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
  renderElements(); // also reverts the select to element.image on failure
  resetRun();
}

/* The accepted decorations, each removable. Shown as a list rather than a count so it is
 * obvious which five went in — a wrong one costs a whole generation to discover. */
function renderElements() {
  const list = $("accepted-elements");
  list.innerHTML = "";
  state.elements.forEach((element, index) => {
    const item = document.createElement("li");
    item.className = needsManualSize(element.code, element.sizeMm, element.manualMm)
      ? "has-warning" : "";
    const top = document.createElement("div");
    top.className = "accepted-item-top";
    const thumbWrap = document.createElement("div");
    thumbWrap.className = "thumb-wrap";
    const thumb = document.createElement("img");
    thumb.src = element.url;
    thumb.className = "checker";
    thumb.alt = `Decoration ${index + 1}`;
    thumbWrap.append(thumb);
    // the code travels with the picture rather than sitting beside it as its own field —
    // picking from the catalogue already supplies it, there is nothing left to fill in
    if (element.code) {
      const badge = document.createElement("span");
      badge.className = "thumb-code";
      badge.textContent = element.code;
      thumbWrap.append(badge);
    }
    const pill = buildDensityPill(element.density || "normal", (level) => {
      element.density = level;
      renderElements();
    });
    const drop = document.createElement("button");
    drop.className = "btn danger";
    drop.textContent = "เอาออก";
    drop.addEventListener("click", () => {
      state.elements.splice(index, 1);
      renderElements();
      resetRun();
    });
    top.append(thumbWrap, pill, drop);
    item.append(top);
    if (element.colours) {
      const select = buildColourSelect(element.colours, element.image, (image) => {
        switchColour(element, image);
      });
      item.append(select);
      enhanceSelect(select); // needs a parent to attach its popup to — must run after append
    }
    const sizeRow = buildSizeRow(element.sizeMm, element.manualMm, (value) => {
      const parsed = Number(value);
      element.manualMm = value && parsed > 0 ? parsed : null;
      refreshGenerateButton();
    });
    item.append(sizeRow);
    // no refreshGenerateButton: a price never gated anything, and filling one in must not
    // start (issue #27)
    item.append(buildPriceRow(element.code, element.price, element.typedPrice, async (value) => {
      try {
        element.typedPrice = await savePrice(element.code, value);
        renderElements();
      } catch (err) {
        showError(err.message);
      }
    }));
    list.append(item);
  });

  const room = MAX_ELEMENTS - state.elements.length;
  $("element-count-hint").textContent = room
    ? `ใส่แล้ว ${state.elements.length} จาก ${MAX_ELEMENTS} ชิ้น`
    : `ครบ ${MAX_ELEMENTS} ชิ้นแล้ว — เอาออกสักชิ้นถ้าจะเปลี่ยน`;
  $("element-file").disabled = room === 0;
}

/* The chip shows the pipeline state of the current run, so it is only reset when the user
 * changes an input — that is the moment the previous run stops being the current one. */
function resetRun() {
  state.requestId = null;
  state.quantities = null;
  $("out-result").hidden = true;
  $("result-actions").hidden = true;
  $("result-quantities").hidden = true;
  $("result-stock").hidden = true;
  $("stock-note").hidden = true;
  $("count-actions").hidden = true;
  $("count-note").hidden = true;
  $("result-empty").hidden = false;
  showError("");
  if (state.treeFile && state.elements.length) setStatus("pending");
  else setStatus("waiting", "รอต้นเปล่ากับของตกแต่งอย่างน้อย 1 ชิ้น");
  refreshGenerateButton();
}

/* The pre-generate estimate, in the confirm dialog: how many of this product fit on a tree
 * that size, from the catalogue millimetres. Not reused against the finished picture — see
 * the count button at the bottom of this file for why those are two different numbers.
 * Indexed against state.elements since that is the order /api/prepare received them in. An
 * entry is null when that item has no catalogue size — suggest_quantity() has no fallback for
 * that case the way scale_sentence() does, so the item is skipped rather than invented. */
function renderQuantities(target, quantities) {
  target.innerHTML = "";
  let shown = false;
  if (quantities) {
    quantities.forEach((q, i) => {
      if (!q) return;
      const li = document.createElement("li");
      li.textContent = `${state.elements[i].code}: ควรใช้ประมาณ ${q.low}–${q.high} ชิ้นบนต้นนี้`;
      target.append(li);
      shown = true;
    });
  }
  target.hidden = !shown;
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

let sizePresets = []; // [{key, width, height, orientation}] from /api/config, for refreshAutoSize below

const ORIENTATION_TH = { portrait: "แนวตั้ง", landscape: "แนวนอน", square: "จัตุรัส" };

async function loadConfig() {
  const config = await call("/api/config");
  sizePresets = config.sizes;
  MAX_ELEMENTS = config.max_elements;
  renderElements(); // the "ใส่ได้ถึง N ชิ้น" hint was built against the pre-fetch fallback

  const select = $("size-select");
  select.innerHTML = "";
  // "match the scene photo's own ratio" — resolved into a concrete size server-side
  // (fit_custom_size) once a scene reference exists; see refreshAutoSize below for how it
  // gets auto-selected the moment a scene photo is set.
  const auto = document.createElement("option");
  auto.value = "auto";
  auto.textContent = "ตามสัดส่วนรูปบรรยากาศ";
  select.append(auto);
  for (const size of config.sizes) {
    const option = document.createElement("option");
    option.value = size.key;
    option.textContent =
      `${size.key} — ${size.width} × ${size.height} (${ORIENTATION_TH[size.orientation]})`;
    option.selected = size.key === config.default_size;
    select.append(option);
  }
  select.disabled = false;

  const densitySelect = $("density-select");
  densitySelect.innerHTML = "";
  for (const density of config.densities) {
    const option = document.createElement("option");
    option.value = density.key;
    option.textContent = density.label;
    option.selected = density.key === config.default_density;
    densitySelect.append(option);
  }
  densitySelect.disabled = false;

  $("cut-hint").textContent = `ไม่เกิน ${config.max_upload_mb} MB, JPG หรือ PNG`;
}

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

function nearestSizeKey(ratio) {
  if (!sizePresets.length || !ratio) return null;
  // compared in log space so a 2:1 landscape and a 1:2 portrait are equally "far" from
  // square — a plain numeric difference would treat every landscape preset as closer to
  // square than any portrait one just because their ratio values happen to be larger
  let best = null;
  let bestDiff = Infinity;
  for (const preset of sizePresets) {
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
  if (state.sceneRatio) {
    $("size-select").value = "auto";
    return;
  }
  const key = nearestSizeKey(state.treeRatio);
  if (key) $("size-select").value = key;
}

/* Codes are never typed on this page: they ride along with whatever the catalogue picker
 * hands over, and are shown burned onto the preview so they can still be read back.
 * Product.md 8.2 wanted them so the prompt could state real millimetres; a code typed from
 * memory out of ~1,300 was always a wrong order waiting to happen. Settings is where a code
 * gets entered by hand, against the catalogue row it belongs to. */
function showTreeCode(code, sizeMm = null, price = null) {
  state.treeCode = code || null;
  state.treeSizeMm = code ? sizeMm : null;
  state.treeManualMm = null; // a new tree slot starts its own gate over from nothing
  state.treePrice = code ? price : null;
  state.treeTypedPrice = null;
  const badge = $("tree-code-badge");
  badge.textContent = code || "";
  badge.hidden = !code;
  renderTreeSizeGate();
}

function showElementCode(code, sizeMm = null, image = null, price = null) {
  const badge = $("element-code-badge");
  badge.textContent = code || "";
  badge.hidden = !code;
  $("element-preview").dataset.code = code || "";
  $("element-preview").dataset.sizeMm = code && sizeMm != null ? sizeMm : "";
  // "" covers both "no code" and "priced at nothing yet" — the accepted item turns it back
  // into null, which is what buildPriceRow reads as "offer to fill this in" (issue #27)
  $("element-preview").dataset.price = code && price != null ? price : "";
  // Which colour photo this cutout came from (issue #15) — carried from here into the
  // accepted item so its card knows what to offer a colour switcher against. Empty for an
  // uploaded photo, which has no catalogue colours to switch between.
  $("element-preview").dataset.image = image || "";
}

upgradeFilePickers(); // native file inputs say "Choose File" in English; this swaps in a Thai button
renderElements();

/* ---- step 1: bare tree ---- */
$("tree-file").addEventListener("change", async (event) => {
  const file = event.target.files[0] || null;
  state.treeFile = file;
  $("tree-preview-frame").hidden = !file;
  if (file) $("tree-preview").src = URL.createObjectURL(file);
  // an own photo carries no catalogue code, and must not keep the one the picker left behind
  showTreeCode(null);
  state.treeRatio = null;
  if (file) {
    try {
      const { width, height } = await imageDimensions(file);
      state.treeRatio = width / height;
    } catch {
      /* size auto-pick is a convenience; a photo the browser can't measure still uploads fine */
    }
    refreshAutoSize();
  }
  resetRun();
});

/* ---- step 2: element, background removed, previewed, accepted or discarded ---- */
$("element-file").addEventListener("change", (event) => {
  $("cut-btn").disabled = !event.target.files[0];
  $("element-preview-frame").hidden = true;
  $("element-actions").hidden = true;
  showElementCode(null);
  resetRun();
});

function showElementPreview(result, code = null, sizeMm = null, image = null) {
  $("element-preview").src = result.element_url;
  $("element-preview-frame").hidden = false;
  $("element-actions").hidden = false;
  $("element-preview").dataset.name = result.element;
  showElementCode(code, sizeMm, image, result.price ?? null);
}

$("cut-btn").addEventListener("click", async () => {
  const file = $("element-file").files[0];
  if (!file) return;

  $("cut-btn").disabled = true;
  $("cut-btn").textContent = "กำลังตัดพื้นหลัง…";
  showError("");
  try {
    const body = new FormData();
    body.append("files", file);
    showElementPreview(await call("/api/remove-bg", { method: "POST", body }));
  } catch (err) {
    // rembg failed. Nothing continues on its own — the user re-uploads or cuts by hand.
    showError(err.message);
    $("cut-btn").disabled = false;
  } finally {
    $("cut-btn").textContent = "ตัดพื้นหลัง";
  }
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
  card.addEventListener("click", () => catalogPickerCallback(item.code, item.image));
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
  return catalogPickerMode === "element" ? $("backdrop-select").value : "";
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
async function openCatalogPicker(mode, onPick) {
  catalogPickerMode = mode;
  catalogPickerCallback = onPick;
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

$("catalog-toggle").addEventListener("click", () => openCatalogPicker("element", useFromCatalog));
$("tree-catalog-toggle").addEventListener("click", () => openCatalogPicker("tree", useTreeFromCatalog));

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
 * (useFromCatalog) or a later colour switch (switchColour, issue #15) — same code+image pair,
 * same precut-aware endpoint (issue #13: a file read, never a live background removal). */
async function fetchElementFromCatalog(code, image) {
  const body = new FormData();
  body.append("code", code);
  if (image) body.append("image", image);
  return call("/api/element/from-catalog", { method: "POST", body });
}

async function useFromCatalog(code, image) {
  if (catalogBusy) return;
  showError("");
  setCatalogBusy(true, "กำลังตัดพื้นหลัง… ครั้งแรกหลังเปิดโปรแกรมจะนานหน่อย");
  try {
    const result = await fetchElementFromCatalog(code, image);
    showElementPreview(result, code, result.size_mm, image || null);
    $("catalog-dialog").close();
  } catch (err) {
    $("catalog-dialog").close();
    showError(err.message);
  } finally {
    // the count line is rewritten by the next loadCatalogPage, so it only has to stop saying
    // "working" — reopening the picker reloads it anyway
    setCatalogBusy(false);
  }
}

/* Same idea as useFromCatalog, but for the tree slot — no background removal (a tree keeps
 * its own photographed background), so state.treeFile needs a real File the same way
 * #tree-file's own change handler produces one, not just a stored server filename. */
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
    state.treeFile = new File([blob], result.tree, { type: "image/png" });
    $("tree-preview").src = result.tree_url;
    $("tree-preview-frame").hidden = false;
    clearFilePicker($("tree-file"));  // the picker's tree replaces whatever was uploaded
    showTreeCode(code, result.size_mm, result.price ?? null);
    try {
      const { width, height } = await imageDimensions(state.treeFile);
      state.treeRatio = width / height;
      refreshAutoSize();
    } catch {
      /* size auto-pick is a convenience */
    }
    $("catalog-dialog").close();
    resetRun();
  } catch (err) {
    $("catalog-dialog").close();
    showError(err.message);
  } finally {
    setCatalogBusy(false);
  }
}

$("accept-btn").addEventListener("click", async () => {
  const preview = $("element-preview");
  const code = preview.dataset.code || "";
  const image = preview.dataset.image || "";
  // Fetched once, up front, rather than per render: a card only ever needs this list to
  // build its switcher (issue #15), and re-fetching on every renderElements() call would ask
  // the same question dozens of times over a session. A product with only one colour comes
  // back with exactly one entry, which is also the "offer no switcher" signal downstream.
  let colours = null;
  if (code) {
    try {
      const found = await call(`/api/catalog/products/${encodeURIComponent(code)}/colours`);
      if (found.colours.length > 1) colours = found.colours;
    } catch {
      /* the switcher is a convenience; a decoration must still be accepted without it */
    }
  }
  state.elements.push({
    name: preview.dataset.name,
    url: preview.src,
    code,
    image: image || null,
    colours,
    sizeMm: code && preview.dataset.sizeMm ? Number(preview.dataset.sizeMm) : null,
    manualMm: null,
    price: code && preview.dataset.price ? Number(preview.dataset.price) : null,
    typedPrice: null,
    density: "normal",
  });
  // clear the slot so the next decoration starts from nothing
  clearFilePicker($("element-file"));
  $("element-preview-frame").hidden = true;
  $("element-actions").hidden = true;
  $("cut-btn").disabled = true;
  showElementCode(null);
  renderElements();
  resetRun();
});

/* AC-2: a bad cut-out is a dead end the user can back out of, not something they have to
 * ride to the end of the pipeline. */
$("reject-btn").addEventListener("click", () => {
  clearFilePicker($("element-file"));
  $("element-preview-frame").hidden = true;
  $("element-actions").hidden = true;
  $("cut-btn").disabled = true;
  showElementCode(null);
  resetRun();
});

/* ---- step 3: the optional scene/ambience reference ----
 * Uploaded on its own endpoint rather than with the tree, because it is not
 * background-removed: its background is the only thing being taken from it. Independent of
 * the find-from-photo page (identify.html/identify.js) — this one only ever feeds the
 * background of the generated result, never the catalogue search. */
$("scene-reference-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  showError("");
  try {
    const body = new FormData();
    body.append("files", file);
    const result = await call("/api/reference", { method: "POST", body });
    state.sceneReference = result.reference;
    $("scene-reference-preview").src = result.reference_url;
    $("scene-reference-preview").hidden = false;
    $("scene-reference-actions").hidden = false;
    try {
      const { width, height } = await imageDimensions(file);
      state.sceneRatio = width / height;
      refreshAutoSize();
    } catch {
      /* size auto-pick is a convenience */
    }
  } catch (err) {
    showError(err.message);
    clearFilePicker($("scene-reference-file"));
  }
  resetRun();
});

$("scene-reference-clear").addEventListener("click", () => {
  state.sceneReference = null;
  state.sceneRatio = null;
  clearFilePicker($("scene-reference-file"));
  $("scene-reference-preview").hidden = true;
  $("scene-reference-actions").hidden = true;
  refreshAutoSize(); // falls back to the tree photo's own ratio, if any
  resetRun();
});

/* ---- sample pictures ----
 * A shop trying the app for the first time has no bare-tree photo and no room photo to hand,
 * which is two dead ends before it can generate anything. These are committed under
 * frontend/samples/ and served by the existing /static mount, so there is no endpoint here —
 * each one is fetched as a blob and then goes through exactly the path a real upload takes:
 * the tree becomes a File in state.treeFile, the room is POSTed to /api/reference. Nothing
 * downstream can tell a sample from something the user chose, which is the point.
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

function buildSampleStrip(host, folder, samples, onPick) {
  if (host.childElementCount) return;  // built once, on first open
  for (const sample of samples) {
    const url = `/static/samples/${folder}/${sample.file}`;
    const button = document.createElement("button");
    button.type = "button";
    button.title = sample.label;
    const img = document.createElement("img");
    img.src = url;
    img.alt = sample.label;
    // no loading="lazy" here, unlike the catalogue grid: the strip is only built the first
    // time its button is pressed, so these are already fetched on demand — lazy on top of
    // that just leaves them unloaded until the row happens to be scrolled into view.
    button.append(img);
    button.addEventListener("click", () => onPick(url, sample));
    host.append(button);
  }
}

function toggleSampleStrip(host) {
  host.hidden = !host.hidden;
}

async function fetchSampleFile(url, type = "image/jpeg") {
  const blob = await (await fetch(url)).blob();
  return new File([blob], url.split("/").pop(), { type });
}

$("tree-sample-toggle").addEventListener("click", () => {
  const host = $("tree-samples");
  buildSampleStrip(host, "trees", SAMPLE_TREES, async (url) => {
    showError("");
    try {
      state.treeFile = await fetchSampleFile(url);
      $("tree-preview").src = url;
      $("tree-preview-frame").hidden = false;
      clearFilePicker($("tree-file"));
      showTreeCode(null);
      const { width, height } = await imageDimensions(state.treeFile);
      state.treeRatio = width / height;
      refreshAutoSize();
      host.hidden = true;
      resetRun();
    } catch (err) {
      showError(err.message);
    }
  });
  toggleSampleStrip(host);
});

$("scene-sample-toggle").addEventListener("click", () => {
  const host = $("scene-samples");
  buildSampleStrip(host, "scenes", SAMPLE_SCENES, async (url) => {
    showError("");
    try {
      const sceneFile = await fetchSampleFile(url);
      const body = new FormData();
      body.append("files", sceneFile);
      const result = await call("/api/reference", { method: "POST", body });
      state.sceneReference = result.reference;
      $("scene-reference-preview").src = result.reference_url;
      $("scene-reference-preview").hidden = false;
      $("scene-reference-actions").hidden = false;
      clearFilePicker($("scene-reference-file"));
      const { width, height } = await imageDimensions(sceneFile);
      state.sceneRatio = width / height;
      refreshAutoSize();
      host.hidden = true;
      resetRun();
    } catch (err) {
      showError(err.message);
    }
  });
  toggleSampleStrip(host);
});

/* ---- step 4 + 5: prepare, confirm, generate ---- */
$("generate-btn").addEventListener("click", async () => {
  state.busy = true;
  refreshGenerateButton();
  showError("");

  // all the codes or none: a partial set cannot produce a ratio and the server refuses it,
  // and it is no longer something the user could complete by hand (see exactScaleReady)
  const exact = exactScaleReady();
  const droppedCodes = !exact
    && (Boolean(state.treeCode) || state.elements.some((element) => element.code));

  try {
    const body = new FormData();
    body.append("files", state.treeFile);
    body.append("backdrop", $("backdrop-select").value);
    body.append("size", $("size-select").value);
    if ($("size-select").value === "auto") {
      body.append("scene_ratio", String(state.sceneRatio || state.treeRatio || ""));
    }
    body.append("density", $("density-select").value);
    body.append("tree_code", exact ? state.treeCode : "");
    body.append("tree_manual_mm", state.treeManualMm != null ? String(state.treeManualMm) : "");
    if (state.sceneReference) body.append("reference", state.sceneReference);
    for (const element of state.elements) {
      body.append("element", element.name);
      body.append("element_code", exact ? element.code : "");
      // Travels with the code, never without it (issue #16) — a colour is only meaningful
      // paired with the product it names one photo of (ADR-0002), same "all codes or none"
      // gate `exact` already applies to element_code above.
      body.append("element_image", exact ? (element.image || "") : "");
      body.append("element_manual_mm", element.manualMm != null ? String(element.manualMm) : "");
      body.append("element_density", element.density || "");
    }

    const prepared = await call("/api/prepare", { method: "POST", body });
    state.requestId = prepared.request_id;
    setStatus("pending");
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

    const missingBox = $("confirm-missing-sizes");
    missingBox.textContent = prepared.missing_sizes.length
      ? `แคตตาล็อกไม่มีขนาดของ: ${prepared.missing_sizes.join(", ")} — ขนาดชิ้นนี้จะไม่ตรงของจริง`
      : "";
    missingBox.hidden = !prepared.missing_sizes.length;

    state.quantities = prepared.quantities || null;
    renderQuantities($("confirm-quantities"), state.quantities);

    $("confirm-btn").disabled = false;
    $("confirm-dialog").showModal();
  } catch (err) {
    showError(err.message);
    state.busy = false;
    refreshGenerateButton();
  }
});

$("cancel-btn").addEventListener("click", () => {
  $("confirm-dialog").close();
  state.requestId = null;
  state.busy = false;
  refreshGenerateButton();
});

$("confirm-btn").addEventListener("click", async () => {
  // first line of defence against a double-click; the server's claim() is the second
  $("confirm-btn").disabled = true;
  $("confirm-dialog").close();
  setStatus("calling_api");

  try {
    // What went into this run is already visible in panels 1 and 2 (the tree preview and
    // the accepted-decorations list) — repeating them here would just be the same pictures
    // twice, so the result panel shows only the thing this step actually produced.
    const result = await call(`/api/generate/${state.requestId}`, { method: "POST" });
    showTotals(result.totals);
    $("out-result").src = result.output_url;
    $("out-result").hidden = false;
    $("result-empty").hidden = true;
    // the pre-generate suggestion is not shown against the finished picture: it answers "how
    // many fit on a tree this size" from the catalogue millimetres, and the picture routinely
    // does not honour that scale. Counting the picture itself is the button below.
    $("count-actions").hidden = false;
    // What to pull off the shelf, which is a different question from what the picture shows —
    // labelled as such, right where the shop finishes a job (issue #25).
    renderStock(result.elements);
    $("download-btn").href = result.output_url;
    $("result-meta").textContent =
      `${result.request_id} · ${result.size} · ${result.usage ? result.usage.total_tokens.toLocaleString() + " โทเคน" : "ไม่ทราบต้นทุน"}`;
    $("result-actions").hidden = false;
    setStatus("api_success");

    // tell the server the browser really got it, so a row left at api_success is a genuine
    // "paid for, never seen" case and not just a page that forgot to say so (Spec.md 7)
    await call(`/api/delivered/${state.requestId}`, { method: "POST" }).catch(() => {});
    setStatus("delivered");
  } catch (err) {
    setStatus("api_failed");
    showError(err.message);
  } finally {
    state.busy = false;
    refreshGenerateButton();
    refreshTotals();
  }
});

/* ---- how many are actually in the finished picture ----
 * A separate, billed vision call, so it is a button rather than something that runs itself
 * after every generation — same rule the catalogue search follows. What it answers is the
 * question the shop quotes from: the size-based suggestion says how many would fit on a tree
 * that size, the picture regularly shows a different number, and the customer is looking at
 * the picture. */
$("count-btn").addEventListener("click", async () => {
  if (!state.requestId) return;
  const button = $("count-btn");
  button.disabled = true;
  button.textContent = "กำลังนับ…";
  showError("");

  try {
    const counted = await call(`/api/count/${state.requestId}`, { method: "POST" });
    const list = $("result-quantities");
    list.innerHTML = "";
    for (const kind of counted.kinds) {
      const li = document.createElement("li");
      li.textContent = `${kind.summary}: ${kind.count} ชิ้น`;
      list.append(li);
    }
    if (!counted.kinds.length) {
      const li = document.createElement("li");
      li.textContent = "ไม่เจอของตกแต่งในรูปนี้";
      list.append(li);
    }
    list.hidden = false;
    $("count-note").textContent = counted.note;
    $("count-note").hidden = false;
  } catch (err) {
    showError(err.message);
  } finally {
    button.disabled = false;
    button.textContent = "นับของในรูปนี้";
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

/* ---- mode switch — one primitive shared by every mode's own button/container pair, so
 * auto.js and prompt.js each only have to say which name is theirs. Reuses the sidebar
 * nav's .row/.row.active pattern for "which is active", the same reasoning auto.js's own
 * comment already gives: Generate is the one control allowed the primary-button colour on
 * this page (test_ui_design_system.py rule 4), and a mode tab is navigation, not that. */
const MODES = [
  { name: "custom", btn: "mode-btn-custom", panel: "mode-custom" },
  { name: "prompt", btn: "mode-btn-prompt", panel: "mode-prompt" },
  { name: "auto", btn: "mode-btn-auto", panel: "mode-auto" },
];
function showMode(name) {
  for (const mode of MODES) {
    const active = mode.name === name;
    $(mode.btn).classList.toggle("active", active);
    $(mode.btn).setAttribute("aria-pressed", String(active));
    $(mode.panel).hidden = !active;
  }
}
$("mode-btn-custom").addEventListener("click", () => showMode("custom"));
