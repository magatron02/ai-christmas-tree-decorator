/* "Prompt mode" — a third way in, chat-style: attach tree/decorations/scene as chips (same
 * catalogue-or-upload mechanics as "กำหนดเอง"), type a free description instead of picking a
 * density, send once. The typed text replaces the whole density system for this request —
 * backend/main.py's /api/generate substitutes it straight into {density}, after the prompt
 * template's own hard preservation rules, never before them.
 *
 * Independent of app.js's `state` — this page's own attachments never touch the accepted-
 * elements list or panel 1/2, and nothing here runs unless "Prompt mode" is the active tab.
 */

const promptState = {
  attachments: [], // {role: "tree"|"element"|"scene", file, url, code, sizeMm, manualMm}
  maxChars: 500,   // overwritten by /api/config's prompt_mode_max_chars once it loads
  sending: false,
};

function promptTree() {
  return promptState.attachments.find((a) => a.role === "tree") || null;
}
function promptScene() {
  return promptState.attachments.find((a) => a.role === "scene") || null;
}
function promptElements() {
  return promptState.attachments.filter((a) => a.role === "element");
}

/* ---- rendering ---- */
function renderPromptAttachments() {
  const host = $("prompt-attachments");
  host.innerHTML = "";
  promptState.attachments.forEach((a, i) => {
    const chip = document.createElement("div");
    chip.className = `composer-chip ${a.role === "tree" ? "is-tree" : ""}`;

    const thumb = document.createElement("div");
    thumb.className = "thumb";
    const img = document.createElement("img");
    img.src = a.url;
    img.alt = a.code || a.role;
    img.style.cssText = "width:100%;height:100%;object-fit:contain";
    thumb.append(img);

    const meta = document.createElement("div");
    meta.className = "meta";
    const codeSpan = document.createElement("span");
    codeSpan.className = "code";
    codeSpan.textContent = a.code || (a.role === "scene" ? "รูปบรรยากาศ" : "รูปที่อัปโหลด");
    const roleSpan = document.createElement("span");
    roleSpan.className = "role";
    roleSpan.textContent = a.role === "tree" ? "ต้นไม้" : a.role === "scene" ? "บรรยากาศ" : "ของตกแต่ง";
    meta.append(codeSpan, roleSpan);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove";
    remove.setAttribute("aria-label", "เอาออก");
    remove.textContent = "✕";
    remove.addEventListener("click", () => {
      promptState.attachments.splice(i, 1);
      renderPromptAttachments();
      refreshPromptSend();
    });

    chip.append(thumb, meta, remove);

    // the exact size-gate row app.js's own panels use (buildSizeRow: hidden once the code
    // has a catalogue size, a warning + input otherwise). Elements always get the row, same
    // as renderElements(); the tree only gets one when it has a catalogue code, same as
    // renderTreeSizeGate() — an uploaded tree/scene photo carries no code to gate on.
    if (a.role === "element" || (a.role === "tree" && a.code)) {
      const sizeRow = buildSizeRow(a.sizeMm, a.manualMm, (value) => {
        const parsed = Number(value);
        a.manualMm = value && parsed > 0 ? parsed : null;
        refreshPromptSend();
      });
      chip.append(sizeRow);
    }

    host.append(chip);
  });
}

function refreshPromptSend() {
  const ready = promptTree() && promptElements().length > 0
    && !promptState.attachments.some((a) => needsManualSize(a.code, a.sizeMm, a.manualMm));
  $("prompt-send").disabled = !ready || promptState.sending;
}

/* ---- attaching: upload direct, or the shared catalogue picker (app.js's openCatalogPicker,
 * generalised this session to take any onPick callback instead of a hardcoded if/else) ---- */
async function attachTreeFromCatalog(code, image) {
  const body = new FormData();
  body.append("code", code);
  if (image) body.append("image", image);
  const result = await call("/api/tree/from-catalog", { method: "POST", body });
  // /api/prepare's "files" field wants a real File, the same way useTreeFromCatalog (app.js)
  // builds one for panel 1 — fetched once now rather than re-fetched at send time
  const blob = await (await fetch(result.tree_url)).blob();
  const file = new File([blob], result.tree, { type: "image/png" });
  promptState.attachments = promptState.attachments.filter((a) => a.role !== "tree");
  promptState.attachments.unshift({
    role: "tree", code, file, url: result.tree_url, sizeMm: result.size_mm, manualMm: null,
  });
  $("catalog-dialog").close();
  renderPromptAttachments();
  refreshPromptSend();
}

async function attachElementFromCatalog(code, image) {
  const body = new FormData();
  body.append("code", code);
  if (image) body.append("image", image);
  const result = await call("/api/element/from-catalog", { method: "POST", body });
  promptState.attachments.push({
    // .name is the stored filename /api/prepare's "element" field wants verbatim, the same
    // way state.elements[].name already is in app.js — never re-uploaded
    role: "element", code, name: result.element, url: result.element_url,
    sizeMm: result.size_mm, manualMm: null,
  });
  $("catalog-dialog").close();
  renderPromptAttachments();
  refreshPromptSend();
}

$("prompt-attach-tree").addEventListener("click", () => {
  openCatalogPicker("tree", attachTreeFromCatalog);
  // clicking "แนบต้นไม้" opens the catalogue by default; the hidden file input beside it
  // covers "upload my own photo" without a second dialog to choose between them up front —
  // same two-entry-point pattern panel 1 already uses (its own button + its own file input)
});
$("prompt-tree-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  const url = URL.createObjectURL(file);
  promptState.attachments = promptState.attachments.filter((a) => a.role !== "tree");
  promptState.attachments.unshift({
    role: "tree", file, code: null, url, sizeMm: null, manualMm: null,
  });
  renderPromptAttachments();
  refreshPromptSend();
});

$("prompt-attach-element").addEventListener("click", () => {
  if (promptElements().length >= MAX_ELEMENTS) return;
  openCatalogPicker("element", attachElementFromCatalog);
});
$("prompt-element-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file || promptElements().length >= MAX_ELEMENTS) return;
  showError("");
  try {
    const body = new FormData();
    body.append("files", file);
    const result = await call("/api/remove-bg", { method: "POST", body });
    promptState.attachments.push({
      role: "element", code: null, name: result.element, url: result.element_url,
      sizeMm: null, manualMm: null,
    });
    renderPromptAttachments();
    refreshPromptSend();
  } catch (err) {
    showError(err.message);
  }
});

$("prompt-attach-scene").addEventListener("click", () => {
  $("prompt-scene-file").click();
});
$("prompt-scene-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  showError("");
  try {
    const body = new FormData();
    body.append("files", file);
    const result = await call("/api/reference", { method: "POST", body });
    promptState.attachments = promptState.attachments.filter((a) => a.role !== "scene");
    promptState.attachments.push({
      role: "scene", code: null, name: result.reference, url: result.reference_url,
    });
    renderPromptAttachments();
    refreshPromptSend();
  } catch (err) {
    showError(err.message);
  }
});

/* ---- composer text + size ---- */
const promptTextarea = $("prompt-textarea");
const promptCharCount = $("prompt-char-count");
promptTextarea.addEventListener("input", () => {
  const n = promptTextarea.value.length;
  promptCharCount.textContent = `${n} / ${promptState.maxChars}`;
  promptCharCount.classList.toggle("near-limit", n > promptState.maxChars * 0.9);
});

let promptConfigLoaded = false;
async function loadPromptConfig() {
  if (promptConfigLoaded) return;
  const config = await call("/api/config");
  promptState.maxChars = config.prompt_mode_max_chars;
  promptTextarea.maxLength = config.prompt_mode_max_chars;
  promptCharCount.textContent = `0 / ${config.prompt_mode_max_chars}`;

  const select = $("prompt-size-select");
  select.innerHTML = "";
  for (const size of config.sizes) {
    const option = document.createElement("option");
    option.value = size.key;
    option.textContent = `${size.key} (${ORIENTATION_TH[size.orientation]})`;
    option.selected = size.key === config.default_size;
    select.append(option);
  }
  select.disabled = false;
  promptConfigLoaded = true;
}

/* ---- send: /api/prepare (tree as a real File, element/reference as the stored filenames
 * their attach step already got back — never re-uploaded), then this page's own confirm
 * dialog (kept separate from app.js's #confirm-dialog, see index.html's comment), then
 * /api/generate + /api/delivered exactly as app.js's own flow does. ---- */
let promptRequestId = null;

// all codes or none: catalog.scale_sentence can't compute a ratio from a partial set, and
// /api/prepare refuses a request whose element codes are partially filled (backend/main.py's
// api_prepare) — same rule and same reasoning as app.js's own exactScaleReady()
function promptExactScaleReady() {
  const tree = promptTree();
  const elements = promptElements();
  return Boolean(tree && tree.code) && elements.length > 0 && elements.every((e) => e.code);
}

$("prompt-send").addEventListener("click", async () => {
  promptState.sending = true;
  refreshPromptSend();
  showError("");
  try {
    const tree = promptTree();
    const elements = promptElements();
    const scene = promptScene();
    const exact = promptExactScaleReady();

    const body = new FormData();
    body.append("files", tree.file);
    body.append("size", $("prompt-size-select").value);
    body.append("density", "normal"); // irrelevant once custom_prompt wins server-side
    body.append("tree_code", exact ? tree.code : "");
    body.append("tree_manual_mm", tree.manualMm != null ? String(tree.manualMm) : "");
    body.append("custom_prompt", promptTextarea.value.trim());
    if (scene) body.append("reference", scene.name);
    for (const element of elements) {
      body.append("element", element.name);
      body.append("element_code", exact ? element.code : "");
      body.append("element_manual_mm", element.manualMm != null ? String(element.manualMm) : "");
      body.append("element_density", "normal");
    }

    const prepared = await call("/api/prepare", { method: "POST", body });
    promptRequestId = prepared.request_id;

    const scenePhrase = prepared.reference_url ? "ต้นจะย้ายไปอยู่ในสถานที่ตามรูปอ้างอิง" : "ต้นจะอยู่บนพื้นหลังเดิม";
    $("prompt-confirm-body").textContent =
      `สร้างภาพ ${prepared.width} × ${prepared.height} หนึ่งภาพ พร้อมของตกแต่ง ${prepared.element_count} ชิ้นผสมกัน · ` +
      `${scenePhrase} · เสียเงินเฉพาะตอนที่ได้ภาพกลับมา`;
    const preview = $("prompt-confirm-preview");
    const text = promptTextarea.value.trim();
    preview.textContent = text ? `“${text}”` : "";
    preview.hidden = !text;
    $("prompt-confirm-dialog").showModal();
  } catch (err) {
    showError(err.message);
  } finally {
    promptState.sending = false;
    refreshPromptSend();
  }
});

$("prompt-confirm-no").addEventListener("click", () => {
  $("prompt-confirm-dialog").close();
});

// the composer text is arbitrary user input rendered back via innerHTML — escape it (and any
// other value that isn't already known-safe markup) before it lands in a bubble
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function promptBubble(role, html) {
  const msg = document.createElement("div");
  msg.className = `msg ${role}`;
  msg.innerHTML = html;
  $("prompt-log").append(msg);
  $("prompt-log").scrollTop = $("prompt-log").scrollHeight;
  return msg;
}

$("prompt-confirm-yes").addEventListener("click", async () => {
  $("prompt-confirm-dialog").close();
  const requestId = promptRequestId;
  const attachments = promptState.attachments;
  const text = promptTextarea.value.trim();

  const chips = attachments.map((a) => `
    <div class="attach-thumb ${a.role === "tree" ? "is-tree" : ""}">
      <img src="${a.url}" alt="${escapeHtml(a.code || a.role)}" style="width:100%;height:100%;object-fit:contain">
    </div>`).join("");
  promptBubble("user",
    `<div class="msg-attachments">${chips}</div>` +
    (text ? `<div class="msg-bubble">${escapeHtml(text)}</div>`
          : `<div class="msg-bubble hint">(ไม่ได้พิมพ์อะไร — ใช้ความหนาแน่น "ปกติ")</div>`));

  const bot = promptBubble("bot",
    `<div class="msg-bubble"><span class="typing-dots"><span></span><span></span><span></span></span> กำลังสร้างภาพ…</div>`);

  // clear the composer immediately — Send is single-shot, ready for the next one while this
  // one is still generating
  promptState.attachments = [];
  promptTextarea.value = "";
  promptCharCount.textContent = `0 / ${promptState.maxChars}`;
  renderPromptAttachments();
  refreshPromptSend();

  try {
    const result = await call(`/api/generate/${requestId}`, { method: "POST" });
    showTotals(result.totals);
    bot.innerHTML = `
      <div class="msg-bubble" style="max-width:340px">
        เสร็จแล้ว
        <img class="msg-result-img" alt="ต้นที่แต่งแล้ว" src="${result.output_url}">
        <div class="msg-meta">${result.size} · ${result.usage ? result.usage.total_tokens.toLocaleString() + " โทเคน" : "ไม่ทราบต้นทุน"}</div>
      </div>`;
    await call(`/api/delivered/${requestId}`, { method: "POST" }).catch(() => {});
  } catch (err) {
    bot.innerHTML = `<div class="msg-bubble">สร้างภาพไม่สำเร็จ: ${escapeHtml(err.message)}</div>`;
  } finally {
    $("prompt-log").scrollTop = $("prompt-log").scrollHeight;
    refreshTotals();
  }
});

/* ---- mode switch ---- */
$("mode-btn-prompt").addEventListener("click", async () => {
  showMode("prompt");
  showError("");
  try {
    await loadPromptConfig();
  } catch (err) {
    showError(err.message);
  }
  refreshPromptSend();
});
