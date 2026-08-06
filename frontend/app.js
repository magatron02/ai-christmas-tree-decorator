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
  pending: ["", "Ready to generate"],
  calling_api: ["running", "Calling gpt-image-2…"],
  api_success: ["done", "Image generated"],
  api_failed: ["failed", "Generation failed — nothing was billed"],
  delivered: ["done", "Delivered"],
};

const MAX_ELEMENTS = 5;

const state = {
  treeFile: null,
  elements: [], // {name, url, code} — one entry per accepted cut-out, up to MAX_ELEMENTS
  reference: null, // stored filename of the optional setting photo
  requestId: null,
  busy: false,
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

async function call(url, options) {
  const response = await fetch(url, options);
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    /* a non-JSON body means the server fell over; the status line still tells us enough */
  }
  if (!response.ok) throw new Error(payload.error || `${response.status} ${response.statusText}`);
  return payload;
}

function refreshGenerateButton() {
  $("generate-btn").disabled = !(state.treeFile && state.elements.length) || state.busy;
}

/* The accepted decorations, each removable. Shown as a list rather than a count so it is
 * obvious which five went in — a wrong one costs a whole generation to discover. */
function renderElements() {
  const list = $("accepted-elements");
  list.innerHTML = "";
  state.elements.forEach((element, index) => {
    const item = document.createElement("li");
    const thumb = document.createElement("img");
    thumb.src = element.url;
    thumb.className = "checker";
    thumb.alt = `Decoration ${index + 1}`;
    const label = document.createElement("span");
    label.className = "mono";
    label.textContent = element.code || `#${index + 1}`;
    const drop = document.createElement("button");
    drop.className = "btn danger";
    drop.textContent = "remove";
    drop.addEventListener("click", () => {
      state.elements.splice(index, 1);
      renderElements();
      resetRun();
    });
    item.append(thumb, label, drop);
    list.append(item);
  });

  const room = MAX_ELEMENTS - state.elements.length;
  $("element-count-hint").textContent = room
    ? `${state.elements.length} of ${MAX_ELEMENTS} added. Each one is cut out separately so you can check it.`
    : `${MAX_ELEMENTS} of ${MAX_ELEMENTS} added — remove one to swap it.`;
  $("element-file").disabled = room === 0;
  $("element-code").disabled = room === 0;
}

/* The chip shows the pipeline state of the current run, so it is only reset when the user
 * changes an input — that is the moment the previous run stops being the current one. */
function resetRun() {
  state.requestId = null;
  $("result").hidden = true;
  showError("");
  if (state.treeFile && state.elements.length) setStatus("pending");
  else setStatus("waiting", "Waiting for a tree and at least one decoration");
  refreshGenerateButton();
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
  $("cut-hint").textContent = `Runs locally. Costs nothing. Max ${config.max_upload_mb} MB, JPG or PNG.`;
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
            ? `${exact.code} — ${exact.size_raw} (catalogue page ${exact.page})`
            : `${exact.code} — the catalogue prints no size for this one`
          : "";
      } catch {
        /* the picker is a convenience; the server re-checks the code on prepare anyway */
      }
    }, 200);
  });
}

wireCodePicker("tree-code", "tree-code-list", "tree-code-hint");
wireCodePicker("element-code", "element-code-list", "element-code-hint");
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

$("cut-btn").addEventListener("click", async () => {
  const file = $("element-file").files[0];
  if (!file) return;

  $("cut-btn").disabled = true;
  $("cut-btn").textContent = "Removing background…";
  showError("");
  try {
    const body = new FormData();
    body.append("files", file);
    const result = await call("/api/remove-bg", { method: "POST", body });
    $("element-preview").src = result.element_url;
    $("element-preview").hidden = false;
    $("element-actions").hidden = false;
    $("element-preview").dataset.name = result.element;
  } catch (err) {
    // rembg failed. Nothing continues on its own — the user re-uploads or cuts by hand.
    showError(err.message);
    $("cut-btn").disabled = false;
  } finally {
    $("cut-btn").textContent = "Remove background";
  }
});

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

/* ---- step 3: the optional setting reference ----
 * Uploaded on its own endpoint rather than with the tree, because it is not
 * background-removed: its background is the only thing being taken from it. */
$("reference-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  showError("");
  try {
    const body = new FormData();
    body.append("files", file);
    const result = await call("/api/reference", { method: "POST", body });
    state.reference = result.reference;
    $("reference-preview").src = result.reference_url;
    $("reference-preview").hidden = false;
    $("reference-actions").hidden = false;
  } catch (err) {
    showError(err.message);
    $("reference-file").value = "";
  }
  resetRun();
});

$("reference-clear").addEventListener("click", () => {
  state.reference = null;
  $("reference-file").value = "";
  $("reference-preview").hidden = true;
  $("reference-actions").hidden = true;
  resetRun();
});

/* ---- step 4 + 5: prepare, confirm, generate ---- */
$("generate-btn").addEventListener("click", async () => {
  state.busy = true;
  refreshGenerateButton();
  showError("");
  $("result").hidden = true;

  try {
    const body = new FormData();
    body.append("files", state.treeFile);
    body.append("size", $("size-select").value);
    body.append("tree_code", $("tree-code").value.trim());
    if (state.reference) body.append("reference", state.reference);
    for (const element of state.elements) {
      body.append("element", element.name);
      body.append("element_code", element.code);
    }

    const prepared = await call("/api/prepare", { method: "POST", body });
    state.requestId = prepared.request_id;
    setStatus("pending");
    const many = prepared.element_count > 1
      ? `${prepared.element_count} decorations mixed together`
      : `1 decoration`;
    $("confirm-body").textContent =
      `This calls gpt-image-2 and produces one ${prepared.width} × ${prepared.height} image ` +
      `with ${many}. It is billed to your OpenAI account, and only if the image comes back. ` +
      (prepared.reference_url
        ? `The tree will be moved into a new setting taken from your reference photo. `
        : `The tree keeps its own background. `) +
      (prepared.exact_scale
        ? `Sizes come from the catalogue.`
        : `No product codes given, so the sizes are left to the model's judgement.`);
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
    const result = await call(`/api/generate/${state.requestId}`, { method: "POST" });
    showTotals(result.totals);
    $("out-tree").src = result.tree_url;
    const strip = $("out-elements");
    strip.innerHTML = "";
    for (const element of result.elements) {
      const thumb = document.createElement("img");
      thumb.className = "thumb checker";
      thumb.src = element.url;
      thumb.alt = element.code || "Decoration";
      strip.append(thumb);
    }
    $("out-result").src = result.output_url;
    $("download-btn").href = result.output_url;
    $("result-meta").textContent =
      `${result.request_id} · ${result.size} · ${result.usage ? result.usage.total_tokens.toLocaleString() + " tokens" : "cost not reported"}`;
    $("result").hidden = false;
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

loadConfig().catch((err) => showError(err.message));
refreshTotals();
