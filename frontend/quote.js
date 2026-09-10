/* The full decoration-price breakdown for one already-generated request — split out of the
 * main page's panel 4 because panels 1-3 there left it too little room (2026-09-10). Reads
 * everything from GET /api/request/{id}; nothing here talks to /api/prepare or /api/generate.
 *
 * Quantity per decoration comes from one of two sources, the exact one always winning once it
 * exists: an exact per-code count from "นับของในรูปนี้" (row.counted_items if one was already
 * persisted server-side, or a fresh click here — see request_log.set_counted, backend/main.py),
 * otherwise a density-range estimate (config.ELEMENT_DENSITY_QTY_RANGE, mirrored below). Either
 * is multiplied by a user-set multiplier: the picture only shows the tree's front.
 *
 * Price/size for each line already came pre-resolved from the backend (catalogue first for
 * size, vendor wholesale first for price — backend/main.py's _priced_extra) — this page never
 * re-derives either, only presents them and does the quantity x price arithmetic.
 */

const $ = (id) => document.getElementById(id);

function showError(message) {
  const box = $("error-box");
  box.textContent = message;
  box.hidden = !message;
}

async function refreshTotals() {
  try {
    const totals = await call("/api/usage");
    $("generations").textContent = totals.generations;
    $("tokens").textContent = totals.total_tokens.toLocaleString();
  } catch (err) {
    showError(err.message);
  }
}

function money(amount) {
  return `฿${Math.round(amount).toLocaleString("th-TH")}`;
}

// Mirrors backend/config.py's ELEMENT_DENSITY_QTY_RANGE — the per-item quantity estimate used
// before anything has been counted from the picture. Kept in sync by hand, same as app.js
// used to before this page existed.
const ELEMENT_DENSITY_QTY = { light: [1, 6], normal: [8, 12], full: [18, 24] };

let row = null; // the /api/request/{id} response, fetched once on load
let counted = null; // code -> exact count, from row.counted_items or a fresh count click here
let multiplier = 2; // both sides of the tree are decorated but only the front is in frame
let extras = []; // per-element (index-aligned with row.elements) manual add-on, default 0 —
                  // added *after* the multiplier, for a buffer/breakage allowance the shop
                  // wants to buy on top of what the picture actually needs

/* `price` is always exactly as printed — for a pack (element.pack = {qty, unit}, from
 * backend/services/vendor_lookup.py's pack_for()) that is the price of the whole pack, not
 * one piece of it, and a shop cannot buy half a bag: this rounds the pieces needed *up* to
 * whole packs rather than dividing the price down to an invented per-piece figure. `null`
 * pack (an ordinary single-piece or per-tree price) and `{ambiguous: true}` (a price whose
 * own unit column mentions packaging with no size given for it) both cost qty x price
 * directly — the ambiguous case just says so in `note` instead of silently guessing. */
function packCost(qtyMin, qtyMax, price, pack) {
  if (pack && pack.qty) {
    const packsMin = Math.ceil(qtyMin / pack.qty);
    const packsMax = Math.ceil(qtyMax / pack.qty);
    const leftoverMin = packsMin * pack.qty - qtyMin;
    const leftoverMax = packsMax * pack.qty - qtyMax;
    const note = packsMin === packsMax
      ? `ซื้อ ${packsMin} ${pack.unit} (${(packsMin * pack.qty).toLocaleString("th-TH")} ชิ้น)` +
        (leftoverMin > 0 ? ` เหลือ ${leftoverMin.toLocaleString("th-TH")} ชิ้น` : "")
      : `ซื้อ ${packsMin}–${packsMax} ${pack.unit} ` +
        `(${(packsMin * pack.qty).toLocaleString("th-TH")}–${(packsMax * pack.qty).toLocaleString("th-TH")} ชิ้น)`;
    return { costMin: packsMin * price, costMax: packsMax * price, unitLabel: `/${pack.unit}`, note };
  }
  return {
    costMin: qtyMin * price,
    costMax: qtyMax * price,
    unitLabel: "/ชิ้น",
    note: pack && pack.ambiguous
      ? "หน่วยราคาไม่ชัดเจน อาจเป็นราคาต่อแพ็ก ไม่ใช่ต่อชิ้น — ตรวจสอบก่อนสั่งจำนวนมาก"
      : "",
  };
}

/* Thumbnail (the accepted cut-out or tree photo itself — the same image the compositor saw),
 * code, and a Thai name — the catalogue has no name field of its own at all, so `name` is
 * always the vendor's (backend/services/vendor_lookup.py's name_for()), falling back to
 * `fallback` (a label or plain description) for a code it has none for. */
function productCell(imageUrl, code, name) {
  const img = imageUrl
    ? `<img class="quote-thumb checker" src="${imageUrl}" alt="${code || name}">`
    : "";
  // name first and plain-weight — it's what a shop assistant actually calls the thing; the
  // code is only there to pull the right stock, so it takes the muted/small .hint treatment
  // underneath instead of leading.
  const codeLine = code ? `<span class="mono hint">${code}</span>` : "";
  return `<td><div class="btn-row" style="flex-wrap:nowrap">${img}` +
    `<div class="stack" style="gap:2px"><span>${name}</span>${codeLine}</div>` +
    `</div></td>`;
}

function render() {
  const rows = $("quote-rows");
  rows.innerHTML = "";
  const missing = []; // has a catalogue code, but no price from either source
  const noCatalog = []; // no catalogue code at all — an own upload, never priceable
  const m = multiplier > 0 ? multiplier : 1;

  let decorMin = 0;
  let decorMax = 0;
  let totalQtyMin = 0;
  let totalQtyMax = 0;
  let anyEstimated = false;
  let anyVendor = false;

  for (let i = 0; i < row.elements.length; i++) {
    const element = row.elements[i];
    const tr = document.createElement("tr");
    const label = element.label || element.code || "ของตกแต่ง";

    if (!element.code) {
      noCatalog.push(label);
      tr.innerHTML = `${productCell(element.url, null, label)}<td class="mono">—</td><td></td>` +
        `<td class="mono">—</td><td class="mono">ไม่มีในแคตตาล็อก</td><td></td>`;
      rows.append(tr);
      continue;
    }

    const exact = counted ? counted[element.code] : null;
    const [rangeMin, rangeMax] = ELEMENT_DENSITY_QTY[element.density || "normal"] || [null, null];
    const calcMin = (exact != null ? exact : rangeMin) * m;
    const calcMax = (exact != null ? exact : rangeMax) * m;
    if (exact == null) anyEstimated = true;
    const extra = extras[i] || 0;
    const qtyMin = calcMin + extra;
    const qtyMax = calcMax + extra;
    totalQtyMin += qtyMin;
    totalQtyMax += qtyMax;

    // A range only when the two ends actually differ (the estimate case) — an exact count
    // plus a manual "เพิ่มเติม" still lands both ends on the same number (calcMin === calcMax
    // to start with), so it collapsed to "9–9 ชิ้น" here before this checked qtyMin/qtyMax
    // directly instead of re-deriving "is this exact" from exact/extra separately.
    const qtyText = qtyMin === qtyMax
      ? `${qtyMin.toLocaleString("th-TH")} ชิ้น`
      : `${qtyMin.toLocaleString("th-TH")}–${qtyMax.toLocaleString("th-TH")} ชิ้น`;
    const qtyNote = exact == null ? " (ประมาณ)" : "";
    const extraCell = `<td><input type="number" class="input mono" min="0" step="1" ` +
      `value="${extra}" data-extra-index="${i}" style="width:4rem"></td>`;

    if (element.price == null) {
      missing.push(label);
      tr.innerHTML =
        `${productCell(element.url, element.code, element.name || label)}` +
        `<td class="mono">${qtyText}${qtyNote}</td>${extraCell}` +
        `<td class="mono">—</td><td class="mono">ไม่มีราคา</td><td></td>`;
    } else {
      const isVendor = element.price_source === "vendor";
      if (isVendor) anyVendor = true;
      const mark = isVendor ? " †" : "";
      const { costMin, costMax, unitLabel, note } = packCost(qtyMin, qtyMax, element.price, element.pack);
      decorMin += costMin;
      decorMax += costMax;
      const lineText = costMin === costMax ? money(costMin) : `${money(costMin)}–${money(costMax)}`;
      tr.innerHTML =
        `${productCell(element.url, element.code, element.name || label)}` +
        `<td class="mono">${qtyText}${qtyNote}</td>${extraCell}` +
        `<td class="mono">${money(element.price)}${unitLabel}${mark}</td>` +
        `<td class="mono">${lineText}${mark}</td><td class="hint">${note}</td>`;
    }
    rows.append(tr);
    const input = tr.querySelector("input[data-extra-index]");
    if (input) {
      // "change" (fires on blur/Enter), not "input" — render() rebuilds every row from
      // scratch, which would otherwise yank focus out of the field after every keystroke
      input.addEventListener("change", () => {
        extras[i] = Number(input.value) || 0;
        render();
      });
    }
  }

  // Always its own row whenever there is a tree — not just when it has a catalogue code. An
  // own-photo tree used to contribute nothing here silently, which read as "the tree wasn't
  // counted" rather than "the tree is ฿0 because it isn't a catalogue product".
  const treeRow = document.createElement("tr");
  if (!row.tree_code) {
    treeRow.innerHTML =
      `${productCell(row.tree_url, null, "ต้นไม้ (ไม่ได้มาจากแคตตาล็อก)")}` +
      `<td class="mono">1 ต้น</td><td></td><td class="mono">—</td><td class="mono">${money(0)}</td><td></td>`;
  } else if (row.tree_price == null) {
    missing.push(row.tree_label || row.tree_code);
    treeRow.innerHTML =
      `${productCell(row.tree_url, row.tree_code, row.tree_name || row.tree_label || row.tree_code)}` +
      `<td class="mono">1 ต้น</td><td></td><td class="mono">—</td><td class="mono">ไม่มีราคา</td><td></td>`;
  } else {
    const isVendor = row.tree_price_source === "vendor";
    if (isVendor) anyVendor = true;
    const mark = isVendor ? " †" : "";
    treeRow.innerHTML =
      `${productCell(row.tree_url, row.tree_code, row.tree_name || row.tree_label || row.tree_code)}` +
      `<td class="mono">1 ต้น</td><td></td>` +
      `<td class="mono">${money(row.tree_price)}${mark}</td><td class="mono">${money(row.tree_price)}${mark}</td>` +
      `<td></td>`;
  }
  rows.append(treeRow);

  const incomplete = missing.length || noCatalog.length;
  const decorText = decorMin === decorMax ? money(decorMin) : `${money(decorMin)}–${money(decorMax)}`;
  $("quote-decor-total").textContent = incomplete ? `${decorText} *` : decorText;

  // ประเภท counts every decoration row (coded and priced or not) — how many different kinds
  // are on this tree at all; ชิ้น only sums the ones a quantity is actually known for (a
  // code-less upload has none to add), so the two numbers can legitimately disagree.
  const qtyText = totalQtyMin === totalQtyMax
    ? `${totalQtyMin.toLocaleString("th-TH")} ชิ้น`
    : `${totalQtyMin.toLocaleString("th-TH")}–${totalQtyMax.toLocaleString("th-TH")} ชิ้น`;
  $("quote-decor-label").textContent = `รวมของตกแต่ง (${row.elements.length} ประเภท, ${qtyText})`;

  const treeAmount = row.tree_code && row.tree_price != null ? row.tree_price : 0;
  const grandMin = decorMin + treeAmount;
  const grandMax = decorMax + treeAmount;
  const grandText = grandMin === grandMax ? money(grandMin) : `${money(grandMin)}–${money(grandMax)}`;
  $("quote-grand-total").textContent = incomplete ? `${grandText} *` : grandText;

  const notes = [];
  if (anyEstimated) {
    notes.push(
      "* จำนวนบางชิ้นยังเป็นการประมาณจาก density — กด \"นับของในรูปนี้\" ด้านซ้ายเพื่อความแม่นยำ"
    );
  }
  if (anyVendor) {
    notes.push("† ราคาทุนจาก vendor (ร้านยังไม่ได้ตั้งราคาของชิ้นนี้เอง) ไม่ใช่ราคาที่ร้านตั้งเอง");
  }
  if (missing.length) notes.push(`ไม่มีราคาเลย ทั้งแคตตาล็อกและ vendor: ${missing.join(", ")}`);
  if (noCatalog.length) notes.push(`ไม่ได้มาจากแคตตาล็อกเลย (ไม่รวมในราคา): ${noCatalog.join(", ")}`);
  $("quote-note").textContent = notes.join(" — ");
  $("quote-note").hidden = !notes.length;
}

function applyCounted(items, note) {
  counted = Object.fromEntries(items.map((item) => [item.code, item.count]));
  $("quote-count-note").textContent = note || "";
  $("quote-count-note").hidden = !note;
  render();
}

$("quote-multiplier").addEventListener("input", (event) => {
  const value = Number(event.target.value);
  multiplier = value > 0 ? value : 1;
  render();
});

$("quote-count-btn").addEventListener("click", async () => {
  const button = $("quote-count-btn");
  button.disabled = true;
  button.textContent = "กำลังนับ…";
  showError("");
  try {
    const result = await call(`/api/count/${row.request_id}`, { method: "POST" });
    applyCounted(result.items, result.note);
  } catch (err) {
    showError(err.message);
  } finally {
    button.disabled = false;
    button.textContent = "นับของในรูปนี้";
  }
});

// Wherever this page was opened from — the main page's result panel or history's "ข้อมูล" —
// go back there, rather than always landing on / regardless of which one it actually was.
$("back-btn").addEventListener("click", () => history.back());

async function load() {
  const requestId = new URLSearchParams(location.search).get("request_id");
  if (!requestId) {
    showError('ไม่มี request_id — เปิดหน้านี้จากปุ่ม "ดูราคาแบบเต็ม" หลังสร้างภาพเสร็จ');
    return;
  }
  try {
    row = await call(`/api/request/${requestId}`);
  } catch (err) {
    showError(err.message);
    return;
  }
  if (!row.output_url) {
    showError("request นี้ยังไม่มีภาพผลลัพธ์ให้ดูราคา");
    return;
  }

  $("quote-body").hidden = false;
  $("quote-result-image").src = row.output_url;
  $("quote-download").href = row.output_url;
  $("quote-meta").textContent = `${row.request_id} · ${row.size} · ${row.created_at}`;

  if (row.counted_items) applyCounted(row.counted_items);
  else render();
}

load();
refreshTotals();
