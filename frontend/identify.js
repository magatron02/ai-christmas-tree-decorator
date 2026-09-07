/* Find-from-photo: independent of the decorate flow (Product.md 8.3c) — this reference photo
 * is only ever sent to the catalogue-search endpoint below, never attached to /api/prepare. */

const $ = (id) => document.getElementById(id);

let identifyReference = null;

function showError(message) {
  const box = $("error-box");
  box.textContent = message;
  box.hidden = !message;
}

async function refreshTotals() {
  try {
    const totals = await call("/api/usage");
    $("generations").textContent = totals.generations;
    $("tokens").textContent = totals.total_tokens.toLocaleString();
  } catch (err) {
    showError(err.message);
  }
}

/* ---- lightbox: a full-size look at a candidate's photo before deciding ----
 * A corner button, not a click on the card itself — see app.js for the catalogue-picker
 * twin of this; identical in both places, duplicated rather than shared because each page
 * already carries its own self-contained script. */
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

/* ---- optional tree code: enables the quantity estimate below, same field/endpoint app.js's
 * panel 1 uses, duplicated because this page carries its own self-contained script. The
 * datalist is filled from the catalogue rather than typed from memory. */
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
          option.label = [product.size_raw, product.page ? `p.${product.page}` : null]
            .filter(Boolean).join(" · ");
          list.append(option);
        }
        const exact = results.find((p) => p.code.toLowerCase() === query.toLowerCase());
        // pdf_page is null for anything not extracted from a book (the whole second shop),
        // so the page reference is only appended when there actually is one
        $(hintId).textContent = exact
          ? exact.size_raw
            ? `${exact.code} — ${exact.size_raw}` + (exact.page ? ` (หน้า ${exact.page})` : "")
            : `${exact.code} — ไม่มีขนาดในแคตตาล็อก`
          : "";
      } catch {
        /* the picker is a convenience; the server ignores an unrecognised code anyway */
      }
    }, 200);
  });
}

wireCodePicker("identify-tree-code", "identify-tree-code-list", "identify-tree-code-hint");

/* ---- the reference photo ---- */
$("identify-reference-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  showError("");
  try {
    const body = new FormData();
    body.append("files", file);
    const result = await call("/api/reference", { method: "POST", body });
    identifyReference = result.reference;
    $("identify-reference-preview").src = result.reference_url;
    $("identify-reference-preview").hidden = false;
    $("identify-reference-actions").hidden = false;
  } catch (err) {
    showError(err.message);
    $("identify-reference-file").value = "";
  }
});

$("identify-reference-clear").addEventListener("click", () => {
  identifyReference = null;
  $("identify-reference-file").value = "";
  $("identify-reference-preview").hidden = true;
  $("identify-reference-actions").hidden = true;
  $("identify-results").innerHTML = "";
  $("identify-note").hidden = true;
  $("identify-panel").hidden = true;
});

/* ---- what of this does the shop sell? ----
 * Deliberately not automatic: it is a billed call, and NonGoals forbids suggestions the
 * user did not ask for. The results are labelled as the closest products rather than as an
 * identification — measured, a nutcracker matches a Santa at 0.82, so a high score is not
 * the same as the right product. */
$("identify-btn").addEventListener("click", async () => {
  if (!identifyReference) return;
  const button = $("identify-btn");
  button.disabled = true;
  button.textContent = "กำลังค้นแคตตาล็อก…";
  $("identify-note").hidden = true;

  try {
    const treeCode = $("identify-tree-code").value.trim();
    const query = treeCode ? `?tree_code=${encodeURIComponent(treeCode)}` : "";
    const result = await call(`/api/reference/${identifyReference}/analyse${query}`, {
      method: "POST",
    });
    renderIdentified(result);
  } catch (err) {
    $("identify-results").innerHTML = "";
    $("identify-panel").hidden = false;
    $("identify-note").textContent = err.message;
    $("identify-note").hidden = false;
  } finally {
    button.disabled = false;
    button.textContent = "หาว่าในรูปมีของอะไรที่เราขาย";
    refreshTotals();
  }
});

function renderIdentified(result) {
  $("identify-panel").hidden = false;
  $("identify-note").textContent = result.note;
  $("identify-note").hidden = false;

  const host = $("identify-results");
  host.innerHTML = "";

  for (const entry of result.decorations) {
    const block = document.createElement("div");
    block.className = "found";

    const header = document.createElement("div");
    header.className = "seen";
    const chip = document.createElement("span");
    if (entry.refused) {
      chip.className = "chip failed";
      chip.textContent = "ไม่เจอของใกล้เคียง";
    } else {
      // Deliberately the neutral chip. Green would say "this is right", and measured, three
      // of ten matches were wrong at scores as high as the correct ones. The kind field is
      // too coarse to tell them apart — "figure" covers Santa, snowman and nutcracker alike
      // — so nothing here can honestly claim correctness.
      chip.className = "chip";
      chip.textContent = "ใกล้เคียงที่สุดในแคตตาล็อก";
    }
    const said = document.createElement("span");
    said.textContent = entry.seen.summary;
    header.append(chip, said);
    block.append(header);

    if (entry.quantity) {
      const quantity = document.createElement("span");
      quantity.className = "hint";
      quantity.textContent =
        `ต้นนี้ใช้ประมาณ ${entry.quantity.low}–${entry.quantity.high} ชิ้น ` +
        `(ของ ${Math.round(entry.quantity.element_mm)} mm บนต้น ${Math.round(entry.quantity.tree_mm)} mm)`;
      block.append(quantity);
    } else if (entry.quantity_note) {
      const note = document.createElement("span");
      note.className = "hint";
      note.textContent = entry.quantity_note;
      block.append(note);
    }

    const row = document.createElement("div");
    row.className = "candidates";
    for (const candidate of entry.candidates) {
      const card = document.createElement("div");
      card.className = "candidate";
      if (candidate.image) {
        const photo = document.createElement("img");
        photo.src = catalogImageUrl(candidate.image);
        photo.alt = candidate.summary || candidate.code;
        card.append(photo, expandButton(photo.src, photo.alt));
      }
      const code = document.createElement("div");
      code.className = "code";
      code.textContent = `${candidate.code} · ${candidate.score.toFixed(2)}`;
      const why = document.createElement("div");
      why.className = "why";
      // pdf_page is null for anything not extracted from a book (the whole second shop)
      why.textContent = [candidate.kind, candidate.pdf_page ? `หน้า ${candidate.pdf_page}` : null]
        .filter(Boolean).join(" · ");
      card.append(code, why);
      // shape is the field that discriminates: kind lumps every figure together, so a
      // nutcracker and a Santa agree on kind and disagree on shape
      if (candidate.shape_agrees === false) {
        const warn = document.createElement("div");
        warn.className = "chip stale";
        warn.textContent = `รูปทรงเป็น ${candidate.shape || "อย่างอื่น"}`;
        card.append(warn);
      }
      // colour is the other field a shape-only comparison misses — same shape, wrong shade
      // (a gold star and a red star agree on shape and kind, and are still different orders)
      if (candidate.colour_agrees === false) {
        const warn = document.createElement("div");
        warn.className = "chip stale";
        warn.textContent = `สีเป็น ${candidate.primary_colour || "อย่างอื่น"}`;
        card.append(warn);
      }
      row.append(card);
    }
    block.append(row);
    host.append(block);
  }
}

refreshTotals();
