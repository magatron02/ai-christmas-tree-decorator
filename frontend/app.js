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
  calling_api: ["running", "กำลังเรียก gpt-image-2…"],
  api_success: ["done", "ได้ภาพแล้ว"],
  api_failed: ["failed", "สร้างไม่สำเร็จ — ไม่ถูกคิดเงิน"],
  delivered: ["done", "ส่งถึงแล้ว"],
  code_mismatch: ["failed", "ใส่รหัสสินค้าให้ทั้งต้นไม้และของตกแต่งทุกชิ้น หรือลบรหัสออกให้หมด"],
};

const MAX_ELEMENTS = 5;

const state = {
  treeFile: null,
  elements: [], // {name, url, code} — one entry per accepted cut-out, up to MAX_ELEMENTS
  sceneReference: null, // stored filename of the optional scene/ambience photo (used at generate time)
  requestId: null,
  busy: false,
  quantities: null, // prepared.quantities from the last /api/prepare, indexed like state.elements
};

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

/* Mirrors the backend's all-or-nothing rule (catalog.scale_sentence): a code for the tree
 * and every decoration, or none at all — anything in between is refused server-side, so the
 * button catches it before a free /api/prepare round-trip has to say so. Checked live because
 * the catalogue picker fills element-code by itself; without this a decoration picked from
 * catalogue silently blocks generate until the user notices the tree has no code too. */
function codesConsistent() {
  const treeCode = $("tree-code").value.trim();
  const codes = state.elements.map((element) => element.code || "");
  if (!treeCode && !codes.some(Boolean)) return true;
  return Boolean(treeCode) && codes.every(Boolean);
}

function refreshGenerateButton() {
  $("generate-btn").disabled =
    !(state.treeFile && state.elements.length) || !codesConsistent() || state.busy;
}

/* The accepted decorations, each removable. Shown as a list rather than a count so it is
 * obvious which five went in — a wrong one costs a whole generation to discover. */
function renderElements() {
  const list = $("accepted-elements");
  list.innerHTML = "";
  state.elements.forEach((element, index) => {
    const item = document.createElement("li");
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
    const drop = document.createElement("button");
    drop.className = "btn danger";
    drop.textContent = "เอาออก";
    drop.addEventListener("click", () => {
      state.elements.splice(index, 1);
      renderElements();
      resetRun();
    });
    item.append(thumbWrap, drop);
    list.append(item);
  });

  const room = MAX_ELEMENTS - state.elements.length;
  $("element-count-hint").textContent = room
    ? `ใส่แล้ว ${state.elements.length} จาก ${MAX_ELEMENTS} ชิ้น แต่ละชิ้นตัดพื้นหลังแยกกัน จะได้ตรวจทีละอัน`
    : `ครบ ${MAX_ELEMENTS} ชิ้นแล้ว — เอาออกสักชิ้นถ้าจะเปลี่ยน`;
  $("element-file").disabled = room === 0;
  $("element-code").disabled = room === 0;
}

/* The chip shows the pipeline state of the current run, so it is only reset when the user
 * changes an input — that is the moment the previous run stops being the current one. */
function resetRun() {
  state.requestId = null;
  state.quantities = null;
  $("out-result").hidden = true;
  $("result-actions").hidden = true;
  $("result-quantities").hidden = true;
  $("count-actions").hidden = true;
  $("count-note").hidden = true;
  $("result-empty").hidden = false;
  showError("");
  if (!codesConsistent()) setStatus("code_mismatch");
  else if (state.treeFile && state.elements.length) setStatus("pending");
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

async function loadConfig() {
  const config = await call("/api/config");
  const select = $("size-select");
  select.innerHTML = "";
  for (const size of config.sizes) {
    const option = document.createElement("option");
    option.value = size.key;
    option.textContent = `${size.key} — ${size.width} × ${size.height}`;
    option.selected = size.key === config.default_size;
    select.append(option);
  }
  select.disabled = false;
  $("cut-hint").textContent = `ทำในเครื่อง ไม่เสียเงิน · ไม่เกิน ${config.max_upload_mb} MB, JPG หรือ PNG`;
}

/* ---- product codes ----
 * Optional, but they come in pairs: with both, the server can put the real millimetres in
 * the prompt instead of asking for "a believable size" (Product.md 8.2). The datalist is
 * filled from the catalogue rather than typed from memory — 1,092 codes is too many to
 * remember and a mistyped code is a wrong order. */
function wireCodePicker(inputId, listId, hintId) {
  const input = $(inputId);
  let timer;

  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const query = input.value.trim();
      if (query.length < 2) return;
      try {
        const { results } = await call(`/api/products?q=${encodeURIComponent(query)}`);
        const list = $(listId);
        list.innerHTML = "";
        for (const product of results) {
          const option = document.createElement("option");
          option.value = product.code;
          option.label = [product.size_raw, `p.${product.page}`].filter(Boolean).join(" · ");
          list.append(option);
        }
        const exact = results.find((p) => p.code.toLowerCase() === query.toLowerCase());
        $(hintId).textContent = exact
          ? exact.size_raw
            ? `${exact.code} — ${exact.size_raw} (catalogue หน้า ${exact.page})`
            : `${exact.code} — แคตตาล็อกไม่ได้พิมพ์ขนาดของชิ้นนี้ไว้`
          : "";
      } catch {
        /* the picker is a convenience; the server re-checks the code on prepare anyway */
      }
    }, 200);
  });
}

wireCodePicker("tree-code", "tree-code-list", "tree-code-hint");
wireCodePicker("element-code", "element-code-list", "element-code-hint");
$("tree-code").addEventListener("input", () => resetRun());
renderElements();

/* ---- step 1: bare tree ---- */
$("tree-file").addEventListener("change", (event) => {
  const file = event.target.files[0] || null;
  state.treeFile = file;
  const preview = $("tree-preview");
  preview.hidden = !file;
  if (file) preview.src = URL.createObjectURL(file);
  resetRun();
});

/* ---- step 2: element, background removed, previewed, accepted or discarded ---- */
$("element-file").addEventListener("change", (event) => {
  $("cut-btn").disabled = !event.target.files[0];
  $("element-preview").hidden = true;
  $("element-actions").hidden = true;
  resetRun();
});

function showElementPreview(result) {
  $("element-preview").src = result.element_url;
  $("element-preview").hidden = false;
  $("element-actions").hidden = false;
  $("element-preview").dataset.name = result.element;
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
let catalogPickerMode = "element";   // "element" (panel 2, any category) or "tree" (panel 1,
                                      // locked to the tree category — the same dialog serves
                                      // both rather than duplicating the whole grid/search/page

function catalogCard(item) {
  const card = document.createElement("div");
  card.className = "candidate pickable";
  const photo = document.createElement("img");
  photo.src = `/catalog/${item.image}`;
  photo.alt = item.code;
  photo.loading = "lazy";
  const code = document.createElement("div");
  code.className = "code";
  code.textContent = item.size_raw ? `${item.code} — ${item.size_raw}` : item.code;
  card.append(photo, code);
  // the same code appears once per colour, so the card has to say which one it is
  if (item.colours > 1) {
    const which = document.createElement("div");
    which.className = "why";
    which.textContent = `สี ${item.colour} จาก ${item.colours}`;
    card.append(which);
  }
  if (item.image) card.append(expandButton(`/catalog/${item.image}`, item.code));
  card.addEventListener("click", () => {
    if (catalogPickerMode === "tree") useTreeFromCatalog(item.code, item.image);
    else useFromCatalog(item.code, item.image);
  });
  return card;
}

function skeletonCard() {
  const card = document.createElement("div");
  card.className = "candidate candidate-skeleton";
  return card;
}

async function loadCatalogCategories() {
  try {
    const { categories } = await call("/api/catalog/categories");
    const select = $("catalog-category");
    for (const item of categories) {
      const option = document.createElement("option");
      option.value = item.key;
      option.textContent = `${item.label} (${item.count})`;
      select.append(option);
    }
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
 * from one panel's picker to the other's would show the wrong (stale-mode) results. */
async function openCatalogPicker(mode) {
  catalogPickerMode = mode;
  const categorySelect = $("catalog-category");
  // categories have to exist before "tree" can be selected, so this has to be awaited —
  // firing it and moving on left the lock unset on whichever picker opened first
  if (categorySelect.options.length <= 1) await loadCatalogCategories();
  categorySelect.disabled = mode === "tree";
  categorySelect.value = mode === "tree" ? "tree" : "";
  $("catalog-dialog").showModal();
  loadCatalogPage(true);
}

$("catalog-toggle").addEventListener("click", () => openCatalogPicker("element"));
$("tree-catalog-toggle").addEventListener("click", () => openCatalogPicker("tree"));

$("catalog-category").addEventListener("change", () => loadCatalogPage(true));

$("catalog-close").addEventListener("click", () => $("catalog-dialog").close());
$("catalog-more").addEventListener("click", () => loadCatalogPage(false));

$("catalog-search").addEventListener("input", () => {
  clearTimeout(catalogTimer);
  catalogQuery = $("catalog-search").value.trim();
  catalogTimer = setTimeout(() => loadCatalogPage(true), 200);
});

async function useFromCatalog(code, image) {
  showError("");
  try {
    const body = new FormData();
    body.append("code", code);
    if (image) body.append("image", image);
    showElementPreview(await call("/api/element/from-catalog", { method: "POST", body }));
    $("element-code").value = code;
    $("catalog-dialog").close();
  } catch (err) {
    $("catalog-dialog").close();
    showError(err.message);
  }
}

/* Same idea as useFromCatalog, but for the tree slot — no background removal (a tree keeps
 * its own photographed background), so state.treeFile needs a real File the same way
 * #tree-file's own change handler produces one, not just a stored server filename. */
async function useTreeFromCatalog(code, image) {
  showError("");
  try {
    const body = new FormData();
    body.append("code", code);
    if (image) body.append("image", image);
    const result = await call("/api/tree/from-catalog", { method: "POST", body });
    const blob = await (await fetch(result.tree_url)).blob();
    state.treeFile = new File([blob], result.tree, { type: "image/png" });
    $("tree-preview").src = result.tree_url;
    $("tree-preview").hidden = false;
    $("tree-code").value = code;
    $("catalog-dialog").close();
    resetRun();
  } catch (err) {
    $("catalog-dialog").close();
    showError(err.message);
  }
}

$("accept-btn").addEventListener("click", () => {
  const preview = $("element-preview");
  state.elements.push({
    name: preview.dataset.name,
    url: preview.src,
    code: $("element-code").value.trim(),
  });
  // clear the slot so the next decoration starts from nothing
  $("element-file").value = "";
  $("element-code").value = "";
  $("element-code-hint").textContent = "";
  preview.hidden = true;
  $("element-actions").hidden = true;
  $("cut-btn").disabled = true;
  renderElements();
  resetRun();
});

/* AC-2: a bad cut-out is a dead end the user can back out of, not something they have to
 * ride to the end of the pipeline. */
$("reject-btn").addEventListener("click", () => {
  $("element-file").value = "";
  $("element-preview").hidden = true;
  $("element-actions").hidden = true;
  $("cut-btn").disabled = true;
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
  } catch (err) {
    showError(err.message);
    $("scene-reference-file").value = "";
  }
  resetRun();
});

$("scene-reference-clear").addEventListener("click", () => {
  state.sceneReference = null;
  $("scene-reference-file").value = "";
  $("scene-reference-preview").hidden = true;
  $("scene-reference-actions").hidden = true;
  resetRun();
});

/* ---- step 4 + 5: prepare, confirm, generate ---- */
$("generate-btn").addEventListener("click", async () => {
  state.busy = true;
  refreshGenerateButton();
  showError("");

  try {
    const body = new FormData();
    body.append("files", state.treeFile);
    body.append("size", $("size-select").value);
    body.append("tree_code", $("tree-code").value.trim());
    if (state.sceneReference) body.append("reference", state.sceneReference);
    for (const element of state.elements) {
      body.append("element", element.name);
      body.append("element_code", element.code);
    }

    const prepared = await call("/api/prepare", { method: "POST", body });
    state.requestId = prepared.request_id;
    setStatus("pending");
    const many = prepared.element_count > 1
      ? `ของตกแต่ง ${prepared.element_count} ชิ้นผสมกัน`
      : `ของตกแต่ง 1 ชิ้น`;
    $("confirm-body").textContent =
      `จะเรียก gpt-image-2 สร้างภาพ ${prepared.width} × ${prepared.height} หนึ่งภาพ ` +
      `พร้อม${many} · คิดเงินจากบัญชี OpenAI ของคุณ และคิดเฉพาะตอนที่ได้ภาพกลับมา · ` +
      (prepared.reference_url
        ? `ต้นจะถูกย้ายไปอยู่ในสถานที่ใหม่ตามรูปอ้างอิงที่ใส่ไว้ · `
        : `ต้นจะอยู่บนพื้นหลังเดิมของมัน · `) +
      (prepared.exact_scale
        ? `ขนาดมาจากแคตตาล็อกทั้งหมด`
        : prepared.missing_sizes.length
          ? `บางชิ้นแคตตาล็อกไม่มีขนาด — ดูรายการด้านล่าง ชิ้นนั้น model จะกะขนาดเอง`
          : `ไม่ได้ใส่รหัสสินค้า ขนาดจึงขึ้นกับที่ model ตัดสินเอง`);

    const missingBox = $("confirm-missing-sizes");
    missingBox.textContent = prepared.missing_sizes.length
      ? `แคตตาล็อกไม่มีขนาดของ: ${prepared.missing_sizes.join(", ")} — ชิ้นนี้ model จะกะสัดส่วนเอง ไม่ใช่ตัวเลขจริง`
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

loadConfig().catch((err) => showError(err.message));
refreshTotals();
