/* The reconciliation surface (Spec.md 7.3), and now also the spend record.
 *
 * A row stuck at api_success means the server produced and paid for an image the browser
 * never confirmed receiving. A row stuck at calling_api means the process died mid-call.
 * Both are visible here rather than being retried behind the user's back.
 *
 * The token column is what the request actually cost. A row without one cost nothing. */

const $ = (id) => document.getElementById(id);

const CHIP_CLASS = {
  pending: "chip",
  calling_api: "chip running",
  api_success: "chip done",
  api_failed: "chip failed",
  delivered: "chip done",
};

/* The row used to print the raw state name ("api_success", "calling_api"). Same states as
 * app.js's STATE_LABEL, worded for a log rather than for the run in progress. */
const STATUS_LABEL = {
  pending: "ยังไม่ได้สร้าง",
  calling_api: "กำลังสร้าง",
  api_success: "สร้างแล้ว",
  api_failed: "ไม่สำเร็จ — ไม่ถูกคิดเงิน",
  delivered: "ส่งถึงแล้ว",
};

function cell(row, text, className) {
  const td = document.createElement("td");
  if (className) td.className = className;
  td.textContent = text;
  row.append(td);
  return td;
}

/* created_at is stored in UTC (request_log.now()) — shown here as Thai calendar date
 * (พ.ศ., th-TH's own default), 24-hour time, explicitly converted to Thailand's own timezone
 * so it never reads as whatever timezone the viewer's OS happens to be set to (the "(เวลาไทย)"
 * column header says so). Date and time as two separate strings, not one — the caller puts
 * them on their own line each, which is what actually keeps this column narrow: one line
 * of "10 ก.ย. 2569 10:31:58 น." is wider than the column needs to be. */
function formatCreatedAt(iso) {
  try {
    const date = new Date(iso);
    const dateText = date.toLocaleDateString("th-TH", {
      timeZone: "Asia/Bangkok", day: "numeric", month: "short", year: "numeric",
    });
    const timeText = date.toLocaleTimeString("th-TH", {
      timeZone: "Asia/Bangkok", hour: "2-digit", minute: "2-digit", second: "2-digit",
      hour12: false,
    });
    return { dateText, timeText: `${timeText} น.` };
  } catch {
    return { dateText: iso, timeText: "" }; // malformed timestamp still shows something
  }
}

function whenCell(row, request) {
  const td = document.createElement("td");
  td.className = "mono";
  td.style.textAlign = "center";
  const { dateText, timeText } = formatCreatedAt(request.created_at);
  const dateLine = document.createElement("div");
  dateLine.textContent = dateText;
  const timeLine = document.createElement("div");
  timeLine.textContent = timeText;
  td.append(dateLine, timeLine);
  row.append(td);
}

/* ---- the picture each row produced ----
 * A row used to be six columns of text with a download button, so the only way to see what a
 * run actually made was to fetch the file again — several megabytes to answer "was this the
 * good one?". The thumbnail answers it in the table, and clicking opens the real image.
 *
 * The preview is /api/thumbnail, not the stored file scaled down by CSS: at ~3.3 MB each,
 * drawing a hundred postage stamps from the originals would cost more than the download it
 * is there to save. Loaded lazily so only the rows on screen are fetched at all. */
function openLightbox(src, alt) {
  $("lightbox-image").src = src;
  $("lightbox-image").alt = alt;
  $("lightbox-dialog").showModal();
}

$("lightbox-close").addEventListener("click", () => $("lightbox-dialog").close());

function previewCell(row, request) {
  const td = document.createElement("td");
  td.className = "shrink";
  const name = fileNameFrom(request.output_url);
  if (name) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-preview";
    button.title = "ดูรูปเต็ม";
    const img = document.createElement("img");
    img.src = `/api/thumbnail/${name}`;
    img.alt = `ผลลัพธ์ของ ${request.request_id.slice(0, 8)}`;
    img.loading = "lazy";
    button.append(img);
    button.addEventListener("click", () => openLightbox(request.output_url, img.alt));
    td.append(button);
  } else {
    td.textContent = "—";
  }
  row.append(td);
}

/* output_url is "/files/<stored name>"; the thumbnail endpoint takes the name on its own. */
function fileNameFrom(url) {
  return url ? url.split("/").pop() : null;
}

/* Code and colour, side by side (issue #16) — "4400-1, red" is what someone pulls stock
 * against, "4400-1" alone is not when the product was shot in six colours. A run recorded
 * before colours existed (or an item with no code at all) just shows the code, or nothing. */
function itemsCell(row, elements) {
  const td = document.createElement("td");
  const named = elements.filter((e) => e.code);
  td.textContent = named.length
    ? named.map((e) => (e.colour ? `${e.code} (${e.colour})` : e.code)).join(", ")
    : "—";
  row.append(td);
}

function money(amount) {
  return `฿${Math.round(amount).toLocaleString("th-TH")}`;
}

// Mirrors quote.js's own copy of backend/config.py's ELEMENT_DENSITY_QTY_RANGE, and the same
// default multiplier quote.js starts every request at — there is no per-request stored
// multiplier to read back (it is a client-side-only control, never persisted), so this is the
// same estimate a fresh visit to /quote for this request would show before anyone touches it.
const ELEMENT_DENSITY_QTY = { light: [1, 6], normal: [8, 12], full: [18, 24] };
const DEFAULT_MULTIPLIER = 2;

/* Mirrors quote.js's packCost() (2026-09-10): a pack price (element.pack = {qty, unit}) is the
 * price of the whole pack, not one piece of it, so buying rounds *up* to whole packs rather than
 * dividing the price down to an invented per-piece figure. No pack, or a pack whose unit is
 * merely ambiguous ({ambiguous: true}), both cost qty x price directly — this column has no
 * per-row notes to explain the ambiguous case in, but the total itself is the same either way. */
function packCost(qtyMin, qtyMax, price, pack) {
  if (pack && pack.qty) {
    const packsMin = Math.ceil(qtyMin / pack.qty);
    const packsMax = Math.ceil(qtyMax / pack.qty);
    return { costMin: packsMin * price, costMax: packsMax * price };
  }
  return { costMin: qtyMin * price, costMax: qtyMax * price };
}

/* The actual decorate-the-tree estimate — same arithmetic as quote.js's render(), duplicated
 * rather than imported (this app has no build step/shared modules; every page script is
 * standalone by convention). Used to disagree with quote.js on purpose once, when this column
 * only summed one-of-each-code's unit price; that read as two different numbers for the same
 * request with no explanation, so now it is the same question quote.js answers, asked here
 * with quote.js's own default multiplier (and no "เพิ่มเติม" extra, since that control is
 * client-side-only on /quote and never persisted) since this table has no control to change it. */
function decorationTotal(request) {
  const counted = request.counted_items
    ? Object.fromEntries(request.counted_items.map((item) => [item.code, item.count]))
    : null;
  const m = DEFAULT_MULTIPLIER;
  let min = 0;
  let max = 0;
  let anyEstimated = false;
  let anyVendor = false;
  const missing = [];
  const noCatalog = [];

  for (const element of request.elements) {
    const label = element.label || element.code || "ของตกแต่ง";
    if (!element.code) {
      noCatalog.push(label);
      continue;
    }
    if (element.price == null) {
      missing.push(label);
      continue;
    }
    const exact = counted ? counted[element.code] : null;
    const [rangeMin, rangeMax] = ELEMENT_DENSITY_QTY[element.density || "normal"] || [null, null];
    if (exact == null) anyEstimated = true;
    if (element.price_source === "vendor") anyVendor = true;
    const qtyMin = (exact != null ? exact : rangeMin) * m;
    const qtyMax = (exact != null ? exact : rangeMax) * m;
    const { costMin, costMax } = packCost(qtyMin, qtyMax, element.price, element.pack);
    min += costMin;
    max += costMax;
  }

  if (request.tree_code) {
    if (request.tree_price == null) missing.push(request.tree_label || request.tree_code);
    else {
      if (request.tree_price_source === "vendor") anyVendor = true;
      min += request.tree_price;
      max += request.tree_price;
    }
  }

  return { min, max, anyEstimated, anyVendor, incomplete: missing.length > 0 || noCatalog.length > 0, missing, noCatalog };
}

/* What it costs to actually decorate a tree to match the picture — /quote's own total,
 * recomputed here rather than read back from anywhere (nothing about it is stored server-side
 * except the count it may draw on). Live-looked up prices mean a later catalogue/vendor edit
 * shows up on old rows too, same reasoning catalog.decoration_price_total's own comment gives.
 * A "*" plus the title tooltip marks a total missing at least one price; a "†" marks at least
 * one vendor-sourced price; neither ever reads as a complete, all-catalogue figure when it
 * is not. */
function priceCell(row, request) {
  const td = document.createElement("td");
  td.className = "mono";
  // display:flex (.stack) on a <td> itself overrides its table-cell box, which is what made
  // an earlier height:100%/justify-content attempt a no-op — a table cell only reliably
  // matches the row's own height (set by the tallest cell, the thumbnail) while it stays a
  // genuine table-cell. vertical-align is the table-cell-native way to centre content inside
  // that height, so the flex column goes on a plain wrapper div instead of the <td> itself.
  td.style.verticalAlign = "middle";
  td.style.textAlign = "center";
  const wrap = document.createElement("div");
  wrap.className = "stack";

  const totals = decorationTotal(request);
  const price = document.createElement("span");
  const hasTotal = totals.min > 0 || totals.max > 0;
  const text = totals.min === totals.max ? money(totals.min) : `${money(totals.min)}–${money(totals.max)}`;
  price.textContent = hasTotal
    ? `${text}${totals.incomplete ? " *" : ""}${totals.anyVendor ? " †" : ""}`
    : "—";
  const titles = [];
  if (totals.anyEstimated) titles.push("จำนวนบางชิ้นเป็นการประมาณจาก density ยังไม่เคยกดนับของในรูป");
  if (totals.missing.length) titles.push(`ไม่มีราคา: ${totals.missing.join(", ")}`);
  if (totals.noCatalog.length) titles.push(`ไม่ได้มาจากแคตตาล็อก (ไม่รวมในราคา): ${totals.noCatalog.join(", ")}`);
  if (totals.anyVendor) titles.push("† มีบางส่วนเป็นราคาทุนจาก vendor ไม่ใช่ราคาที่ร้านตั้งเอง");
  td.title = titles.join(" — ");
  wrap.append(price);

  // Straight to this request's full price breakdown (quote.html/quote.js) — right under the
  // total it belongs to, rather than sharing the download button's column.
  if (request.output_url) {
    const info = document.createElement("a");
    info.href = `/quote?request_id=${encodeURIComponent(request.request_id)}`;
    info.className = "btn btn-compact";
    info.textContent = "ข้อมูล";
    wrap.append(info);
  }
  td.append(wrap);
  row.append(td);
}

async function load() {
  let data;
  try {
    data = await call("/api/history");
  } catch (err) {
    $("error-box").textContent = err.message;
    $("error-box").hidden = false;
    return;
  }

  $("generations").textContent = data.totals.generations;
  $("tokens").textContent = data.totals.total_tokens.toLocaleString();
  $("empty").hidden = data.requests.length > 0;

  const body = $("rows");
  body.innerHTML = "";
  for (const request of data.requests) {
    const row = document.createElement("tr");
    previewCell(row, request);
    whenCell(row, request);
    cell(row, request.request_id.slice(0, 8), "mono");
    cell(row, request.size, "mono");
    itemsCell(row, request.elements);
    priceCell(row, request);

    const state = document.createElement("td");
    const chip = document.createElement("span");
    chip.className = CHIP_CLASS[request.status] || "chip";
    chip.textContent = STATUS_LABEL[request.status] || request.status;
    chip.title = request.error || "";
    state.append(chip);
    row.append(state);

    cell(row, request.usage ? request.usage.total_tokens.toLocaleString() : "—", "mono");

    const result = document.createElement("td");
    result.className = "shrink";
    if (request.output_url) {
      const link = document.createElement("a");
      link.href = request.output_url;
      link.download = "";
      link.className = "btn btn-compact";
      link.textContent = "ดาวน์โหลด";
      result.append(link);
    } else {
      result.textContent = "—";
    }
    row.append(result);

    body.append(row);
  }
}

load();
