/* "Auto ตามโทน" — a simple helper for a customer who doesn't know what to pick, gated by a
 * 3-step wizard (ไซส์ต้น → งบประมาณ → แนว, wayfinder map #1). "กำหนดเอง" (app.js's own panels)
 * is unchanged and stays the default; this file only ever *populates* app.js's own `state`
 * and calls its existing render/refresh functions, then hands off to the existing
 * prepare -> confirm -> generate flow untouched. Nothing here talks to /api/generate.
 */

const wizard = {
  loaded: false,
  config: null,
  screen: "panel", // "panel" | "tone" — variant B: one panel, no step navigation
  sizeFt: null,
  budget: 0,
  category: null,
  tone: null,
  pick: null,      // last /api/wizard/pick response (tone screen)
  exclude: [],
  preview: null,   // last live /api/wizard/pick response (panel screen, tone omitted)
  previewTimer: null,
};

const WIZARD_BUDGET_QUICKPICK = [3000, 5000, 10000, 20000];

async function loadWizardConfig() {
  if (wizard.loaded) return;
  wizard.config = await call("/api/wizard/config");
  wizard.loaded = true;
}

/* ---- screen 1: variant B — every field visible and editable at once, no steps. A live
 * count (via /api/wizard/pick with tone omitted — see the backend docstring) updates as any
 * field changes, debounced the same way app.js's own catalogue search already is. ---- */
function wizardPanelReady() {
  return wizard.sizeFt != null && wizard.budget > 0 && wizard.category != null;
}

function scheduleWizardPreview() {
  clearTimeout(wizard.previewTimer);
  if (!wizardPanelReady()) {
    wizard.preview = null;
    renderWizardPanel();
    return;
  }
  wizard.previewTimer = setTimeout(async () => {
    const body = new FormData();
    body.append("size_ft", String(wizard.sizeFt));
    body.append("budget", String(wizard.budget));
    body.append("category", wizard.category);
    try {
      wizard.preview = await call("/api/wizard/pick", { method: "POST", body });
    } catch (err) {
      wizard.preview = null;
      wizard.previewError = err.message;
    }
    renderWizardPanel();
  }, 250);
}

function renderWizardPanel() {
  const counts = wizard.config.history_counts || {};
  const preview = wizard.preview;

  const left = `
    <div class="filter-field">
      <label>ไซส์ต้น</label>
      <div class="chip-select" id="wizard-size-chips">
        ${wizard.config.tree_heights.map((h) => `
          <button type="button" data-ft="${h.ft}" aria-pressed="${wizard.sizeFt === h.ft}">
            ${h.ft} Ft. <span class="hint">(${h.mm} มม.)</span>
          </button>`).join("")}
      </div>
    </div>
    <div class="filter-field">
      <label>งบประมาณ (บาท) — รวมทั้งต้นไม้และของตกแต่ง</label>
      <div class="chip-select" id="wizard-budget-chips">
        ${WIZARD_BUDGET_QUICKPICK.map((v) => `
          <button type="button" data-budget="${v}" aria-pressed="${wizard.budget === v}">
            ฿${v.toLocaleString("th-TH")}
          </button>`).join("")}
      </div>
      <input class="input" type="number" id="wizard-budget-input" placeholder="หรือพิมพ์งบเอง"
        style="width:180px;margin-top:var(--space-2)"
        value="${WIZARD_BUDGET_QUICKPICK.includes(wizard.budget) ? "" : (wizard.budget || "")}">
    </div>
    <div class="filter-field">
      <label>แนว — เลือก 1 แนวหลัก</label>
      <div class="chip-select" id="wizard-category-chips">
        ${wizard.config.categories.map((c) => `
          <button type="button" data-category="${c.key}" aria-pressed="${wizard.category === c.key}"
            ${c.count ? "" : "disabled"}>
            ${c.label} (${c.count})
            ${counts[c.key] ? `<span class="hint">· เคยเลือก ${counts[c.key]} ครั้ง</span>` : ""}
          </button>`).join("")}
      </div>
    </div>`;

  const right = !wizardPanelReady()
    ? `<p class="hint">เลือกไซส์ + งบ + แนวให้ครบ เพื่อดูว่ามีของอะไรพร้อมใช้บ้าง</p>`
    : !preview
      ? `<p class="hint">${wizard.previewError || "กำลังค้นหา…"}</p>`
      : `
    <span class="hint">ของที่ตรงเงื่อนไขตอนนี้</span>
    <div class="live-count">${preview.pool_size}<span class="live-count-unit"> ชิ้น</span></div>
    <div class="auto-preview-strip" style="margin-top:var(--space-3)">
      ${preview.decorations.length ? preview.decorations.map((d) => `
        <div class="auto-pick">
          <div class="auto-pick-thumb"><img src="${d.image_url}" alt="${d.code}" style="width:100%;height:100%;object-fit:contain"></div>
          <span class="auto-pick-code"><b>${d.code}</b> · ฿${d.price.toLocaleString("th-TH")}</span>
        </div>`).join("") : `<span class="hint">ยังไม่เข้าเงื่อนไขไหนเลย — ลองขยับงบหรือเปลี่ยนแนว</span>`}
    </div>`;

  $("mode-auto").innerHTML = `
    <div class="card stack" style="gap:var(--space-4)">
      <span class="panel-title">ตั้งเงื่อนไขแพ็กเกจ</span>
      <p class="hint">ปรับได้พร้อมกันทั้งหมด ผลลัพธ์อัปเดตสด ไม่มีขั้นตอนแยก</p>
      <div class="identify-columns">
        <div class="card stack">${left}</div>
        <div class="card">${right}</div>
      </div>
      <div class="btn-row" style="justify-content:flex-end;padding-top:var(--space-2);border-top:1px solid var(--border)">
        <button class="btn" id="wizard-next" ${wizardPanelReady() ? "" : "disabled"}>เลือกโทนสีต่อ →</button>
      </div>
    </div>`;

  for (const button of $("wizard-size-chips").querySelectorAll("button")) {
    button.addEventListener("click", () => {
      wizard.sizeFt = Number(button.dataset.ft);
      scheduleWizardPreview();
    });
  }
  for (const button of $("wizard-budget-chips").querySelectorAll("button")) {
    button.addEventListener("click", () => {
      wizard.budget = Number(button.dataset.budget);
      scheduleWizardPreview();
    });
  }
  $("wizard-budget-input").addEventListener("input", (event) => {
    wizard.budget = Number(event.target.value) || 0;
    scheduleWizardPreview();
  });
  for (const button of $("wizard-category-chips").querySelectorAll("button")) {
    button.addEventListener("click", () => {
      wizard.category = button.dataset.category;
      scheduleWizardPreview();
    });
  }
  $("wizard-next").addEventListener("click", () => {
    if (!wizardPanelReady()) return;
    wizard.screen = "tone";
    wizard.exclude = [];
    renderWizardTone();
  });
}

/* ---- screen 2: tone + preview strip, fed by /api/wizard/pick ---- */
async function runWizardPick(reshuffle) {
  const body = new FormData();
  body.append("size_ft", String(wizard.sizeFt));
  body.append("budget", String(wizard.budget));
  body.append("category", wizard.category);
  body.append("tone", wizard.tone);
  if (reshuffle) for (const code of wizard.exclude) body.append("exclude", code);

  try {
    wizard.pick = await call("/api/wizard/pick", { method: "POST", body });
    if (reshuffle) {
      wizard.exclude.push(...wizard.pick.decorations.map((d) => d.code));
    } else {
      wizard.exclude = wizard.pick.decorations.map((d) => d.code);
    }
  } catch (err) {
    wizard.pick = null;
    wizard.pickError = err.message;
  }
}

function badge(text) {
  return `<span class="chip warn" style="display:inline-block;width:auto;padding:2px 8px;font-size:var(--text-xs)">${text}</span>`;
}

function renderWizardTone() {
  const tones = wizard.config.tones;
  if (!wizard.tone) wizard.tone = tones[0].key;

  const toneRow = `
    <div class="tone-row" id="wizard-tone-row">
      ${tones.map((t) => `
        <div class="tone-card" role="button" tabindex="0" data-tone="${t.key}"
             aria-pressed="${wizard.tone === t.key}">
          <span class="tone-name">${t.label}</span>
        </div>`).join("")}
    </div>`;

  const pick = wizard.pick;
  const warnings = [];
  if (pick && pick.relaxed && pick.relaxed.length) {
    const names = { tone: "โทนสี", category: "แนว" };
    warnings.push(`ของที่หาได้ไม่ตรง${pick.relaxed.map((k) => names[k]).join(" และ ")}ทั้งหมด — ผ่อนเงื่อนไขให้อัตโนมัติ`);
  }
  if (pick && pick.low_pool) {
    warnings.push(`เหลือของที่เข้าเงื่อนไขแค่ ${pick.pool_size} ชิ้น — อาจสุ่มออกมาซ้ำเดิม`);
  }

  const strip = !pick ? `<p class="hint">${wizard.pickError || "กำลังค้นหา…"}</p>` : `
    <div class="auto-preview-strip">
      ${pick.tree ? `
        <div class="auto-pick is-tree">
          <div class="auto-pick-thumb"><img src="${pick.tree.image_url}" alt="${pick.tree.code}" style="width:100%;height:100%;object-fit:contain"></div>
          <span class="auto-pick-code">ต้นไม้<br><b>${pick.tree.code}</b></span>
        </div>` : `<p class="hint">ไม่มีต้นไม้ในระบบที่มีขนาดใกล้เคียง</p>`}
      ${pick.decorations.map((d) => `
        <div class="auto-pick">
          <div class="auto-pick-thumb"><img src="${d.image_url}" alt="${d.code}" style="width:100%;height:100%;object-fit:contain"></div>
          <span class="auto-pick-code"><b>${d.code}</b> · ฿${d.price.toLocaleString("th-TH")}</span>
          ${!d.matches_category ? badge("ไม่ตรงแนว") : ""}
          ${d.matches_tone === false ? badge("ไม่ตรงโทน") : ""}
        </div>`).join("")}
    </div>`;

  $("mode-auto").innerHTML = `
    <div class="card stack" style="gap:var(--space-4)">
      <span class="panel-title">เลือกโทนสี</span>
      ${toneRow}
      ${warnings.map((w) => `<div class="notice warning">${w}</div>`).join("")}
      <div class="btn-row" style="justify-content:space-between">
        <span class="section-title" style="font-size:var(--text-base)">ต้นไม้ + ของตกแต่งที่เลือกให้</span>
        <button class="btn" id="wizard-shuffle">สุ่มใหม่</button>
      </div>
      ${strip}
      <div class="btn-row" style="justify-content:space-between;padding-top:var(--space-2);border-top:1px solid var(--border)">
        <button class="btn" id="wizard-tone-back">← กลับไปแก้ ไซส์/งบ/แนว</button>
        <button class="btn" id="wizard-confirm" ${pick && pick.tree ? "" : "disabled"}>
          ใช้ชุดนี้ →
        </button>
      </div>
    </div>`;

  for (const card of $("wizard-tone-row").querySelectorAll(".tone-card")) {
    card.addEventListener("click", async () => {
      wizard.tone = card.dataset.tone;
      wizard.exclude = [];
      await runWizardPick(false);
      renderWizardTone();
    });
  }
  $("wizard-shuffle").addEventListener("click", async () => {
    await runWizardPick(true);
    renderWizardTone();
  });
  $("wizard-tone-back").addEventListener("click", () => {
    wizard.screen = "panel";
    renderWizardPanel();
  });
  $("wizard-confirm").addEventListener("click", confirmWizardPick);

  if (!pick && !wizard.pickError) {
    runWizardPick(false).then(renderWizardTone);
  }
}

/* ---- hand-off: materialise the pick into app.js's own state, then switch back to the
 * normal panels so staff review it (including the per-item density/size gate) before the
 * existing Generate button. Nothing past this point is wizard-specific code. ---- */
async function confirmWizardPick() {
  const pick = wizard.pick;
  if (!pick || !pick.tree) return;
  $("wizard-confirm").disabled = true;
  $("wizard-confirm").textContent = "กำลังเตรียมรูป…";
  showError("");

  try {
    const treeBody = new FormData();
    treeBody.append("code", pick.tree.code);
    const treeResult = await call("/api/tree/from-catalog", { method: "POST", body: treeBody });
    const treeBlob = await (await fetch(treeResult.tree_url)).blob();
    state.treeFile = new File([treeBlob], treeResult.tree, { type: "image/png" });
    $("tree-preview").src = treeResult.tree_url;
    $("tree-preview-frame").hidden = false;
    $("tree-file").value = "";
    showTreeCode(pick.tree.code, treeResult.size_mm);
    try {
      const { width, height } = await imageDimensions(state.treeFile);
      state.treeRatio = width / height;
      refreshAutoSize();
    } catch { /* size auto-pick is a convenience */ }

    state.elements = [];
    for (const decoration of pick.decorations) {
      const body = new FormData();
      body.append("code", decoration.code);
      const result = await call("/api/element/from-catalog", { method: "POST", body });
      state.elements.push({
        name: result.element,
        url: result.element_url,
        code: decoration.code,
        sizeMm: result.size_mm,
        manualMm: null,
        density: "normal",
      });
    }
    renderElements();
    resetRun();

    // back to the normal panels — pre-filled, reviewable, same Generate button as always
    $("mode-btn-custom").click();
  } catch (err) {
    showError(err.message);
  } finally {
    $("wizard-confirm").disabled = false;
    $("wizard-confirm").textContent = "ใช้ชุดนี้ →";
  }
}

/* ---- mode switch — reuses the sidebar nav's own .row/.row.active pattern for "which is
 * active" rather than the Generate button's colour: Generate is the one control on this page
 * allowed to carry that emphasis (test_ui_design_system.py rule 4 — exactly one per page, and
 * no script may mint another one), and a mode tab is navigation, not a call to action. ---- */
$("mode-btn-custom").addEventListener("click", () => {
  $("mode-btn-custom").classList.add("active");
  $("mode-btn-custom").setAttribute("aria-pressed", "true");
  $("mode-btn-auto").classList.remove("active");
  $("mode-btn-auto").setAttribute("aria-pressed", "false");
  $("mode-custom").hidden = false;
  $("mode-auto").hidden = true;
});

$("mode-btn-auto").addEventListener("click", async () => {
  $("mode-btn-auto").classList.add("active");
  $("mode-btn-auto").setAttribute("aria-pressed", "true");
  $("mode-btn-custom").classList.remove("active");
  $("mode-btn-custom").setAttribute("aria-pressed", "false");
  $("mode-custom").hidden = true;
  $("mode-auto").hidden = false;
  showError("");
  try {
    await loadWizardConfig();
    if (wizard.screen === "panel") renderWizardPanel();
    else renderWizardTone();
  } catch (err) {
    $("mode-auto").innerHTML = `<div class="notice">${err.message}</div>`;
  }
});
