/* "Auto ตามโทน" — the pick-for-me mode, for a customer who doesn't know what they want.
 *
 * One question: the tone. Auto pick fills a fixed recipe of categories and counts (the same
 * one for every tone and every tree) and drops the result into app.js's own `state`, then
 * hands off to the normal panels so the shop reviews it before the existing Generate button.
 * Nothing here talks to /api/generate.
 *
 * The size/budget/category wizard that used to gate this is gone (ADR-0003): only 191 of 829
 * products carry a price, so the budget question was choosing from a quarter of the catalogue
 * while appearing to search all of it. The tree is the shop's own now — panel 1, as always.
 */

const auto = {
  loaded: false,
  config: null,
  tone: null,
  pick: null,      // last /api/auto/pick response
  pickError: null,
  exclude: [],     // codes already shown, so "สุ่มใหม่" avoids repeats where stock allows
};

async function loadAutoConfig() {
  if (auto.loaded) return;
  auto.config = await call("/api/auto/config");
  auto.loaded = true;
}

async function runAutoPick(reshuffle) {
  const body = new FormData();
  body.append("tone", auto.tone);
  if (reshuffle) for (const code of auto.exclude) body.append("exclude", code);

  try {
    auto.pick = await call("/api/auto/pick", { method: "POST", body });
    auto.pickError = null;
    const codes = auto.pick.decorations.map((d) => d.code);
    if (reshuffle) auto.exclude.push(...codes);
    else auto.exclude = codes;
  } catch (err) {
    auto.pick = null;
    auto.pickError = err.message;
  }
}

function autoCategoryLabel(key) {
  const entry = auto.config.recipe.find((r) => r.category === key);
  return entry ? entry.label : key;
}

function renderAuto() {
  const tones = auto.config.tones;
  if (!auto.tone) auto.tone = tones[0].key;

  const toneRow = `
    <div class="tone-row" id="auto-tone-row">
      ${tones.map((t) => `
        <div class="tone-card" role="button" tabindex="0" data-tone="${t.key}"
             aria-pressed="${auto.tone === t.key}">
          <span class="tone-name">${t.label}</span>
        </div>`).join("")}
    </div>`;

  const pick = auto.pick;
  // both shortfalls are the same promise kept: fewer items rather than an off-tone
  // substitution, since the tone is the only thing the shop asked for. Say which categories
  // came up short either way — an unexplained 6-of-8 reads as a bug.
  const shortfalls = pick
    ? [...pick.missing, ...Object.keys(pick.short)].map(autoCategoryLabel)
    : [];
  const warning = shortfalls.length
    ? `โทนนี้มีของไม่ครบในหมวด ${shortfalls.join(", ")} — ` +
      `จัดให้ ${pick.decorations.length} ชิ้นจาก ${pick.requested} ชิ้น`
    : "";

  // a failed pick is an error, not a placeholder — only the still-loading case is a hint
  const strip = !pick ? (
    auto.pickError
      ? `<div class="notice">${auto.pickError}</div>`
      : `<p class="hint">กำลังจัดให้…</p>`
  ) : `
    <div class="auto-preview-strip">
      ${pick.decorations.map((d) => `
        <div class="auto-pick">
          <div class="auto-pick-thumb"><img src="${d.image_url}" alt="${d.code}" class="auto-pick-img"></div>
          <span class="auto-pick-code"><b>${d.code}</b>${d.price != null ? ` · ฿${d.price.toLocaleString("th-TH")}` : ""}</span>
        </div>`).join("")}
    </div>`;

  $("mode-auto").innerHTML = `
    <div class="card stack" style="gap:var(--space-4)">
      <span class="panel-title">เลือกโทนสี แล้วจัดให้เลย</span>
      ${toneRow}
      ${warning ? `<div class="notice warning">${warning}</div>` : ""}
      <div class="btn-row" style="justify-content:space-between">
        <span class="section-title" style="font-size:var(--text-base)">ของตกแต่งที่เลือกให้</span>
        <button class="btn" id="auto-shuffle">สุ่มใหม่</button>
      </div>
      ${strip}
      <p class="hint">ต้นไม้เลือกเองในแผง 1 — ชุดนี้เป็นของตกแต่งอย่างเดียว แก้เพิ่ม/ลบได้ก่อนสร้างภาพ</p>
      <div class="btn-row" style="justify-content:flex-end;padding-top:var(--space-2);border-top:1px solid var(--border)">
        <button class="btn" id="auto-confirm" ${pick && pick.decorations.length ? "" : "disabled"}>
          ใช้ชุดนี้ →
        </button>
      </div>
    </div>`;

  for (const card of $("auto-tone-row").querySelectorAll(".tone-card")) {
    const choose = async () => {
      auto.tone = card.dataset.tone;
      auto.exclude = [];
      await runAutoPick(false);
      renderAuto();
    };
    card.addEventListener("click", choose);
    // the tone row is the whole of this mode's input, and these are divs wearing
    // role="button" — without this a keyboard can focus a tone but never choose one
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        choose();
      }
    });
  }
  $("auto-shuffle").addEventListener("click", async () => {
    await runAutoPick(true);
    renderAuto();
  });
  $("auto-confirm").addEventListener("click", confirmAutoPick);

  if (!pick && !auto.pickError) {
    runAutoPick(false).then(renderAuto);
  }
}

/* ---- hand-off: materialise the pick into app.js's own state, then switch back to the
 * normal panels so staff review it (including the per-item density/size gate) before the
 * existing Generate button. Nothing past this point is auto-specific code. ---- */
async function confirmAutoPick() {
  const pick = auto.pick;
  if (!pick || !pick.decorations.length) return;
  $("auto-confirm").disabled = true;
  $("auto-confirm").textContent = "กำลังเตรียมรูป…";
  showError("");

  try {
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
    $("auto-confirm").disabled = false;
    $("auto-confirm").textContent = "ใช้ชุดนี้ →";
  }
}

/* ---- mode switch — showMode() (app.js) owns showing/hiding every mode's button+container;
 * this only adds what's specific to entering auto pick. ---- */
$("mode-btn-auto").addEventListener("click", async () => {
  showMode("auto");
  showError("");
  try {
    await loadAutoConfig();
    renderAuto();
  } catch (err) {
    $("mode-auto").innerHTML = `<div class="notice">${err.message}</div>`;
  }
});
