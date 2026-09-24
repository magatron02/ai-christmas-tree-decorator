/* "Prompt mode" — a third way in: the same tree, decorations and scene photo as "กำหนดเอง"
 * (they live in the one store, so switching between the two loses nothing), plus a free
 * description typed instead of picking a density. The typed text replaces the whole density
 * system for this request — backend/main.py's /api/generate substitutes it straight into
 * {density}, after the prompt template's own hard preservation rules, never before them.
 *
 * Single-shot: one description, one Generate, the picture on the stage. There is no chat.
 * The panel itself is drawn by render.js (renderPromptPanel) and the request is built in
 * app.js (buildPromptRequest); this file is only the style-reference gallery it links to.
 */

/* ---- style-reference gallery: the 2026 book's own display-gallery photos, pickable in
 * place of an uploaded scene photo (same /api/reference underneath — see
 * setAtmosphereFromFile in app.js). */

let galleryLoaded = false;

async function renderGallery() {
  const grid = $("gallery-results");
  if (galleryLoaded) return;
  const { images } = await call("/api/gallery");
  galleryLoaded = true;
  if (!images.length) {
    grid.innerHTML = '<span class="hint">ยังไม่มีรูปตัวอย่าง</span>';
    return;
  }
  grid.innerHTML = "";
  for (const image of images) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "gallery-item";
    btn.innerHTML = `<img src="${image.url}" alt="รูปตัวอย่างสไตล์การจัด" loading="lazy">`;
    btn.addEventListener("click", async () => {
      showError("");
      try {
        const blob = await fetch(image.url).then((r) => r.blob());
        await setAtmosphereFromFile(new File([blob], image.name, { type: blob.type }));
        $("gallery-dialog").close();
      } catch (err) {
        showError(err.message);
      }
    });
    grid.appendChild(btn);
  }
}

function openGallery() {
  $("gallery-dialog").showModal();
  renderGallery().catch((err) => showError(err.message));
}

$("gallery-close").addEventListener("click", () => $("gallery-dialog").close());
