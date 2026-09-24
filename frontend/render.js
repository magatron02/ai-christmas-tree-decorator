/* render() — the only thing that turns `store` into DOM (SPEC layout v2 §3).
 *
 * The shell (topbar tabs, footer, stage) is static in index.html and only updated here; the
 * sidebar body is rebuilt from the store one panel per mode. Everything below the shared
 * components is a panel or a piece of chrome that reads the store and nothing else — the
 * handlers that change it live in app.js / auto.js / prompt.js and call setStore()/render().
 *
 * Shared components (SPEC §2): StepHeader, BaseCard, DecorationList, DecorationGrid, AddZone.
 * They are used by more than one panel, so a change to how a decoration row or the "add"
 * zone looks is made once.
 */

/* ---- tiny element builder ---- */
function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, value);
  }
  node.append(...children.flat().filter((child) => child != null && child !== false));
  return node;
}

function button(label, onClick, cls = "btn", props = {}) {
  return h("button", { type: "button", class: cls, onclick: onClick, ...props }, label);
}

/* ---- shared components ---- */

/* "1  ฐานภาพ ........ 2 / 10" — the number turns into a tick once the step has what it needs. */
function StepHeader(number, title, { done = false, counter = "" } = {}) {
  return h("div", { class: "step-header" },
    h("span", { class: `step-num${done ? " is-done" : ""}` }, done ? "✓" : String(number)),
    h("span", { class: "panel-title" }, title),
    counter ? h("span", { class: "hint step-count" }, counter) : null);
}

/* Drop zone + [Catalogue] [อัปโหลดรูป]. `extra` is anything that belongs to the same choice
 * (the sample link on the base step, the auto-cut checkbox on decorations). */
function AddZone({ hint, onCatalogue, onUpload, onFiles, extra = [] }) {
  const zone = h("div", { class: "dropzone" },
    h("span", { class: "hint" }, hint),
    h("div", { class: "btn-row" },
      button("Catalogue", onCatalogue),
      button("อัปโหลดรูป", onUpload)),
    ...extra);
  zone.addEventListener("dragover", (event) => { event.preventDefault(); zone.classList.add("is-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("is-over"));
  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    zone.classList.remove("is-over");
    const files = [...event.dataTransfer.files].filter((file) => file.type.startsWith("image/"));
    if (files.length) onFiles(files);
  });
  return zone;
}

function SampleStrip(folder, samples, onPick) {
  return h("div", { class: "sample-strip" }, samples.map((sample) => {
    const url = `/static/samples/${folder}/${sample.file}`;
    return h("button", { type: "button", title: sample.label, onclick: () => onPick(url) },
      h("img", { src: url, alt: sample.label }));
  }));
}

/* The chosen tree/wall: thumbnail, name, "เปลี่ยน", and the size gate + price offer a catalogue
 * code brings with it. */
function BaseCard() {
  const base = store.base;
  const rows = [];
  if (base.code) {
    rows.push(buildSizeRow(base.sizeMm, base.manualMm, (value) => {
      const parsed = Number(value);
      base.manualMm = value && parsed > 0 ? parsed : null;
      renderFooter();
    }));
    rows.push(buildPriceRow(base.code, base.price, base.typedPrice, async (value) => {
      try {
        base.typedPrice = await savePrice(base.code, value);
        render();
      } catch (err) {
        showError(err.message);
      }
    }));
  }
  return h("div", { class: "stack" },
    h("div", { class: "base-card" },
      h("div", { class: "thumb-wrap base-thumb" },
        h("img", { src: base.url, alt: "ต้นเปล่า" }),
        base.code ? h("span", { class: "thumb-code" }, base.code) : null),
      h("div", { class: "base-card-meta" },
        h("span", { class: "base-card-name" }, base.code || "รูปที่อัปโหลด"),
        h("span", { class: "hint" }, store.backdrop === "wall" ? "ผนัง หรือ ประตู" : "ต้นคริสต์มาส")),
      button("เปลี่ยน", clearBase)),
    ...rows);
}

function BackdropSwitch() {
  return h("div", { class: "mode-switch segmented", role: "tablist", "aria-label": "ฐานภาพ" },
    ["tree", "wall"].map((type) => h("button", {
      type: "button",
      class: `row${store.backdrop === type ? " active" : ""}`,
      "aria-pressed": String(store.backdrop === type),
      onclick: () => setBackdrop(type),
    }, type === "tree" ? "ต้นคริสต์มาส" : "ผนัง")));
}

/* A base step with nothing chosen yet: the same drop zone the decorations get, plus the sample
 * photos (they used to sit on the main page for everybody; they only matter to someone with no
 * photo to hand, which is exactly this state). */
function BaseAddZone() {
  const samples = store.ui.samples;
  return AddZone({
    hint: store.backdrop === "wall" ? "รูปผนัง หรือประตู" : "รูปต้นเปล่า",
    onCatalogue: () => openCatalogPicker("tree", useTreeFromCatalog),
    onUpload: () => $("base-file").click(),
    onFiles: (files) => setBaseFromFile(files[0]),
    extra: [
      button("หรือใช้รูปตัวอย่าง", () => setStore({ ui: { ...store.ui, samples: !samples } }), "btn ghost"),
      samples ? SampleStrip("trees", SAMPLE_TREES, useSampleTree) : null,
    ],
  });
}

function BaseSlot() {
  return store.base ? BaseCard() : BaseAddZone();
}

/* The decoration rows: thumbnail + code, density, colour switch, size gate, price offer, and
 * for an uploaded photo the cut-out status. `compact` (Prompt mode) drops density, colour and
 * price — the size gate stays, because it blocks Generate in every mode. */
function DecorationList({ compact = false } = {}) {
  const list = h("ul", { class: "accepted", id: "accepted-elements" });
  store.decorations.forEach((element, index) => {
    const item = h("li", {
      class: needsManualSize(element.code, element.sizeMm, element.manualMm) ? "has-warning" : "",
    });
    const thumb = h("div", { class: "thumb-wrap" },
      h("img", { src: element.url, class: "checker", alt: `Decoration ${index + 1}` }),
      element.code ? h("span", { class: "thumb-code" }, element.code) : null);
    const top = h("div", { class: "accepted-item-top" }, thumb);
    if (!compact && element.status === "ready") {
      top.append(buildDensityPill(element.density || "normal", (level) => {
        element.density = level;
        render();
      }));
    }
    top.append(button("เอาออก", () => removeDecoration(index), "btn danger"));
    item.append(top);

    const status = decorationStatus(element);
    if (status) item.append(h("span", { class: `hint decoration-status is-${element.status}` }, status));
    if (element.status === "pending") item.append(button("ตัดพื้นหลัง", () => cutDecoration(element)));

    if (element.status === "ready") {
      if (!compact && element.colours) {
        const select = buildColourSelect(element.colours, element.image, (image) => switchColour(element, image));
        item.append(select);
        enhanceSelect(select); // needs a parent to attach its popup to — must run after append
      }
      item.append(buildSizeRow(element.sizeMm, element.manualMm, (value) => {
        const parsed = Number(value);
        element.manualMm = value && parsed > 0 ? parsed : null;
        renderFooter();
      }));
      // a price never gated anything, and filling one in must not start Generate (issue #27)
      if (!compact) {
        item.append(buildPriceRow(element.code, element.price, element.typedPrice, async (value) => {
          try {
            element.typedPrice = await savePrice(element.code, value);
            render();
          } catch (err) {
            showError(err.message);
          }
        }));
      }
    }
    list.append(item);
  });
  return list;
}

function decorationStatus(element) {
  if (element.status === "cutting") return "กำลังตัดพื้นหลัง…";
  if (element.status === "pending") return "ยังไม่ได้ตัดพื้นหลัง";
  if (element.status === "failed") return element.error || "ตัดพื้นหลังไม่สำเร็จ";
  // a catalogue photo arrives already cut; only an upload has a cut-out step worth reporting
  return element.code ? "" : "ตัดพื้นหลังแล้ว";
}

/* The decoration add zone, shared by Custom and Prompt. Gone once the list is full. */
function DecorationAddZone() {
  if (store.decorations.length >= store.limits.maxElements) return null;
  const autoCut = h("input", { type: "checkbox", id: "auto-cut" });
  autoCut.checked = store.ui.autoCut;
  autoCut.addEventListener("change", () => { store.ui.autoCut = autoCut.checked; });
  return AddZone({
    hint: "ลากรูปมาวาง หรือเลือกจาก catalogue",
    onCatalogue: () => openCatalogPicker("element", addDecorationFromCatalog,
      () => store.decorations.map((e) => ({ code: e.code, url: e.url }))),
    onUpload: () => $("element-file").click(),
    onFiles: addDecorationFiles,
    extra: [h("label", { class: "check-row" }, autoCut, " ตัดพื้นหลังอัตโนมัติ")],
  });
}

/* Auto's proposal as a picture grid: five across, plus a "+" tile while there is room. */
function DecorationGrid() {
  const grid = h("div", { class: "decoration-grid" });
  for (const element of store.decorations) {
    grid.append(h("div", { class: "grid-cell" },
      h("div", { class: "thumb-wrap" }, h("img", { src: element.url, class: "checker", alt: element.code || "" })),
      h("span", { class: "grid-code" }, element.code || "")));
  }
  if (store.decorations.length < store.limits.maxElements) {
    grid.append(button("+", () => openCatalogPicker("element", addDecorationFromCatalog,
      () => store.decorations.map((e) => ({ code: e.code, url: e.url }))), "btn grid-add",
    { "aria-label": "เพิ่มของตกแต่ง" }));
  }
  return grid;
}

/* ---- atmosphere reference (Custom step 3; Prompt's "สถานที่จริง" slot) ---- */
function AtmosphereBody() {
  const ref = store.atmosphereRef;
  if (ref) {
    return h("div", { class: "stack" },
      h("img", { class: "thumb-sm", src: ref.url, alt: "รูปบรรยากาศอ้างอิง" }),
      h("div", { class: "btn-row" }, button("เอารูปออก", clearAtmosphere, "btn danger")));
  }
  const samples = store.ui.sceneSamples;
  return h("div", { class: "stack" },
    h("span", { class: "hint" }, "รูปสถานที่ที่อยากให้ต้นไปอยู่"),
    h("div", { class: "btn-row" },
      button("อัปโหลดรูป", () => $("atmosphere-file").click()),
      button("รูปตัวอย่าง", () => setStore({ ui: { ...store.ui, sceneSamples: !samples } }))),
    samples ? SampleStrip("scenes", SAMPLE_SCENES, useSampleScene) : null);
}

function AtmosphereStep() {
  const details = h("details", { class: "card atmosphere-step" },
    h("summary", {},
      h("span", { class: "panel-title" }, "บรรยากาศอ้างอิง"),
      h("span", { class: "hint" }, "ไม่บังคับ")),
    AtmosphereBody());
  details.open = store.ui.atmosphereOpen || Boolean(store.atmosphereRef);
  details.addEventListener("toggle", () => { store.ui.atmosphereOpen = details.open; });
  return details;
}

/* ---- panels ---- */
function renderCustomPanel() {
  const count = store.decorations.length;
  $("panel-custom").replaceChildren(
    h("section", { class: "card stack" },
      StepHeader(1, "ฐานภาพ", { done: Boolean(store.base) }),
      BackdropSwitch(),
      BaseSlot()),
    h("section", { class: "card stack role-decoration" },
      StepHeader(2, "ของตกแต่ง", { done: count > 0, counter: `${count} / ${store.limits.maxElements}` }),
      DecorationList(),
      DecorationAddZone()),
    AtmosphereStep());
}

function renderAutoPanel() {
  const auto = store.auto;
  const panel = $("panel-auto");
  const tones = auto.config ? auto.config.tones : [];
  const count = store.decorations.length;

  const toneGrid = h("div", { class: "tone-grid" }, tones.map((tone) => h("button", {
    type: "button",
    class: "tone-card",
    "aria-pressed": String(store.tone === tone.key),
    onclick: () => chooseTone(tone.key),
  }, tone.label, h("span", { class: "swatches", "aria-hidden": "true" },
    (tone.colours || []).map((name) => h("span", { class: "swatch", style: `background: var(--swatch-${name})` }))))));

  const shortfalls = auto.pick
    ? [...auto.pick.missing, ...Object.keys(auto.pick.short)].map(autoCategoryLabel)
    : [];

  panel.replaceChildren(
    h("section", { class: "card stack" },
      StepHeader(1, "ฐานภาพ", { done: Boolean(store.base) }),
      BaseSlot()),
    h("section", { class: "card stack" },
      StepHeader(2, "โทนสี", { done: Boolean(store.tone) }),
      auto.pickError ? h("div", { class: "notice" }, auto.pickError) : null,
      tones.length ? toneGrid : h("span", { class: "hint" }, "กำลังโหลดโทนสี…")),
    h("section", { class: "card stack role-decoration" },
      StepHeader(3, "ของตกแต่งที่เลือกให้", { done: count > 0, counter: `${count} / ${store.limits.maxElements}` }),
      shortfalls.length
        ? h("div", { class: "notice warning" },
          `โทนนี้มีของไม่ครบในหมวด ${shortfalls.join(", ")} — จัดให้ ${auto.pick.decorations.length} ชิ้นจาก ${auto.pick.requested} ชิ้น`)
        : null,
      auto.preparing ? h("span", { class: "hint" }, "กำลังเตรียมรูป…") : null,
      store.tone ? button("สุ่มใหม่", shuffleAuto, "btn", { id: "auto-shuffle", disabled: auto.preparing }) : null,
      count ? DecorationGrid() : h("span", { class: "hint" }, "เลือกโทนสีเพื่อให้ระบบจัดของตกแต่งให้")));
}

const PROMPT_SUGGESTIONS = [
  "โทนแดงทอง หรูหรา",
  "เว้นระยะห่างพอสมควร",
  "แน่นเต็มต้น",
  "โปร่ง เห็นกิ่งชัด",
  "โทนธรรมชาติ อบอุ่น",
];

function renderPromptPanel() {
  const max = store.limits.promptMaxChars;
  const textarea = h("textarea", {
    class: "composer-textarea", id: "prompt-textarea", rows: "5", maxlength: String(max),
    placeholder: "อยากได้แบบไหน เช่น “แต่งโทนแดง-ทอง หรูหรา เว้นระยะห่างพอสมควร”",
  });
  textarea.value = store.prompt;
  const counter = h("span", { class: "char-count", id: "prompt-char-count" }, `${store.prompt.length} / ${max}`);
  textarea.addEventListener("input", () => {
    store.prompt = textarea.value;
    counter.textContent = `${store.prompt.length} / ${max}`;
    counter.classList.toggle("near-limit", store.prompt.length > max * 0.9);
    renderFooter();
  });

  const chips = h("div", { class: "suggestion-row" }, PROMPT_SUGGESTIONS.map((text) => button(text, () => {
    const joined = store.prompt.trim() ? `${store.prompt.trim()} ${text}` : text;
    setStore({ prompt: joined.slice(0, max) });
  }, "btn suggestion")));

  $("panel-prompt").replaceChildren(
    h("section", { class: "card stack" },
      h("div", { class: "step-header" },
        h("span", { class: "panel-title" }, "แนบภาพ"),
        button("ใช้ชุดตัวอย่าง", openGallery, "btn ghost")),
      h("span", { class: "section-title" }, "ต้นไม้ ", h("span", { class: "hint" }, "จำเป็น")),
      BaseSlot(),
      h("span", { class: "section-title" }, "ของตกแต่ง ",
        h("span", { class: "hint" }, `จำเป็น · ${store.decorations.length} / ${store.limits.maxElements}`)),
      DecorationList({ compact: true }),
      DecorationAddZone(),
      h("span", { class: "section-title" }, "สถานที่จริง ", h("span", { class: "hint" }, "ไม่บังคับ")),
      AtmosphereBody()),
    h("section", { class: "card stack" },
      h("span", { class: "panel-title" }, "อยากได้แบบไหน"),
      textarea,
      chips,
      counter));
}

/* ---- shell chrome ---- */
function renderModeTabs() {
  for (const mode of ["custom", "prompt", "auto"]) {
    const active = store.mode === mode;
    $(`mode-btn-${mode}`).classList.toggle("active", active);
    $(`mode-btn-${mode}`).setAttribute("aria-pressed", String(active));
    $(`panel-${mode}`).hidden = !active;
  }
}

function renderFooter() {
  const sizeSelect = $("size-select");
  if (sizeSelect.options.length !== store.config.sizes.length + 1) {
    sizeSelect.innerHTML = "";
    // "match the scene photo's own ratio" — resolved into a concrete size server-side
    // (fit_custom_size) once a scene reference exists
    sizeSelect.append(new Option("ตามสัดส่วนรูปบรรยากาศ", "auto"));
    for (const size of store.config.sizes) {
      sizeSelect.append(new Option(
        `${size.key} — ${size.width} × ${size.height} (${ORIENTATION_TH[size.orientation]})`, size.key));
    }
  }
  const densitySelect = $("density-select");
  if (densitySelect.options.length !== store.config.densities.length) {
    densitySelect.innerHTML = "";
    for (const density of store.config.densities) densitySelect.append(new Option(density.label, density.key));
  }
  const loaded = store.config.sizes.length > 0;
  sizeSelect.disabled = !loaded || store.busy;
  densitySelect.disabled = !loaded || store.busy;
  if (sizeSelect.value !== store.output.ratio) sizeSelect.value = store.output.ratio;
  if (densitySelect.value !== store.output.density) densitySelect.value = store.output.density;
  // Prompt mode's typed text replaces the density system server-side, so there is nothing to choose
  densitySelect.closest(".select-wrap").hidden = store.mode === "prompt";

  const missing = missingForGenerate();
  $("generate-btn").disabled = missing.length > 0 || store.busy;
  $("generate-btn").textContent = store.busy ? "กำลังสร้างภาพ…" : "สร้างภาพ";

  // the chip is the pipeline state of the current run; before there is a run it says what is
  // still missing (SPEC §5), so a disabled Generate never has to be guessed at
  if (store.status !== "idle") setStatus(store.status);
  else if (missing.length) setStatus("waiting", `ยังขาด: ${missing.join(", ")}`);
  else setStatus("pending");

  $("auto-refine-link").hidden = store.mode !== "auto";
  $("work-body").inert = store.busy;
}

function renderStage() {
  const base = store.base;
  $("stage-original-frame").hidden = !base;
  $("stage-original-empty").hidden = Boolean(base);
  if (base) {
    if ($("stage-original").getAttribute("src") !== base.url) $("stage-original").src = base.url;
    $("stage-original-code").textContent = base.code || "";
    $("stage-original-code").hidden = !base.code;
  }

  const view = store.ui.stageView;
  for (const [name, panel] of [["original", "stage-view-original"], ["result", "stage-view-result"]]) {
    $(`stage-tab-${name}`).classList.toggle("active", view === name);
    $(`stage-tab-${name}`).setAttribute("aria-pressed", String(view === name));
    $(panel).hidden = view !== name;
  }

  const generating = store.busy && store.status === "calling_api";
  $("stage-spinner").hidden = !generating;
  $("stage-status").textContent = generating ? "กำลังสร้างภาพ…" : "";

  renderResult();
}

function renderResult() {
  const result = store.result;
  $("out-result").hidden = !result;
  $("result-empty").hidden = Boolean(result) || (store.busy && store.status === "calling_api");
  $("result-actions").hidden = !result;
  $("count-actions").hidden = !result;
  $("quote-link").hidden = !result;

  const counted = store.run.counted;
  const list = $("result-quantities");
  list.innerHTML = "";
  if (counted) {
    for (const item of counted.items) {
      list.append(h("li", {}, `${item.code}: ${item.count} ชิ้น`));
    }
    if (!counted.items.length) list.append(h("li", {}, "ไม่เจอของตกแต่งในรูปนี้"));
  }
  list.hidden = !counted;
  $("count-note").textContent = counted && counted.note ? counted.note : "";
  $("count-note").hidden = !(counted && counted.note);

  if (!result) {
    $("result-stock").hidden = true;
    $("stock-note").hidden = true;
    return;
  }
  if ($("out-result").getAttribute("src") !== result.output_url) $("out-result").src = result.output_url;
  $("download-btn").href = result.output_url;
  $("quote-link").href = `/quote?request_id=${encodeURIComponent(result.request_id)}`;
  const priceText = result.price_total || (result.price_missing && result.price_missing.length)
    ? ` · ฿${result.price_total.toLocaleString("th-TH")}` + (result.price_missing.length ? " (ราคาไม่ครบ)" : "")
    : "";
  $("result-meta").textContent =
    `${result.request_id} · ${result.size} · ` +
    (result.usage ? result.usage.total_tokens.toLocaleString() + " โทเคน" : "ไม่ทราบต้นทุน") + priceText;
  // what to pull off the shelf, which is a different question from what the picture shows
  // (issue #25) — a request resumed from history has no such list
  renderStock(result.resumed ? [] : result.elements);
}

function render() {
  if (!document.body || !$("panel-custom")) return;
  renderModeTabs();
  if (store.mode === "custom") renderCustomPanel();
  else if (store.mode === "auto") renderAutoPanel();
  else renderPromptPanel();
  renderFooter();
  renderStage();
}

document.addEventListener("DOMContentLoaded", render);
