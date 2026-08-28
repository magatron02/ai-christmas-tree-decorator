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
      link.className = "btn";
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
