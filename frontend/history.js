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
  td.className = "shrink stack";
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
    // under the thumbnail rather than in the result column — the two used to sit side by
    // side with "จัดการต่อ" there and read as one crowded, overlapping row of buttons.
    const link = document.createElement("a");
    link.href = request.output_url;
    link.download = "";
    link.className = "btn";
    link.textContent = "ดาวน์โหลด";
    td.append(link);
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

/* Retail value of the decorations, not the OpenAI cost (that's the token column). Live-looked
 * up against the catalogue on every /api/history read, so a later price edit shows up on old
 * rows too — same reasoning as `price` never being snapshotted anywhere else in the app. A
 * "*" plus the title tooltip marks a total that skipped at least one unpriced decoration,
 * so it never reads as a complete price when it isn't (mirrors missing_sizes elsewhere). */
function priceCell(row, request) {
  const td = document.createElement("td");
  td.className = "mono";
  // "†" if any of the total came from the vendor's own wholesale price rather than a price
  // the shop set itself (backend/services/vendor_prices.py) — same idea as the "*" for a
  // skipped decoration, so the number never reads as one plain thing when it is not.
  const anyVendor = request.elements.some((e) => e.price_source === "vendor")
    || request.tree_price_source === "vendor";
  td.textContent = request.price_total
    ? `฿${request.price_total.toLocaleString("th-TH")}` +
      `${request.price_missing.length ? " *" : ""}${anyVendor ? " †" : ""}`
    : "—";
  const titles = [];
  if (request.price_missing.length) titles.push(`ไม่มีราคา: ${request.price_missing.join(", ")}`);
  if (anyVendor) titles.push("† มีบางส่วนเป็นราคาทุนจาก vendor ไม่ใช่ราคาที่ร้านตั้งเอง");
  td.title = titles.join(" — ");
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
    cell(row, request.created_at, "mono");
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
      // Back to the main page's panels with this request's tree, decorations and result
      // pre-filled — for counting the picture again or re-checking the price breakdown
      // without redoing the whole pick (index.html/app.js's resumeFromHistory()). Download
      // lives under the thumbnail instead (previewCell) — the two used to crowd this one
      // column and overlap.
      const resume = document.createElement("a");
      resume.href = `/?request_id=${encodeURIComponent(request.request_id)}`;
      resume.className = "btn";
      resume.textContent = "จัดการต่อ";
      result.append(resume);
    } else {
      result.textContent = "—";
    }
    row.append(result);

    body.append(row);
  }
}

load();
