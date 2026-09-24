/* Settings — Product.md 8.4.
 *
 * The API key is write-only here as much as on the server: the input is emptied the moment
 * it is sent, nothing ever reads a key back, and the only thing displayed is whether one
 * exists. NonGoals 10 fixed those rules before this page was written. */

const $ = (id) => document.getElementById(id);

/* ---- tabs: ทั่วไป / catalog / ข้อมูลราคาจากซัพพลายเออร์ — same primitive as index.html's mode
 * switch (app.js's MODES/showMode), reusing the sidebar nav's .row/.row.active pair rather
 * than inventing a second way to say "which is active" (test_ui_design_system.py rule 4 keeps
 * .btn.primary to one real action per page; a tab is navigation, not that). */
const SETTINGS_TABS = [
  { name: "general", btn: "settings-tab-general", panel: "settings-panel-general" },
  { name: "catalog", btn: "settings-tab-catalog", panel: "settings-panel-catalog" },
  { name: "vendor", btn: "settings-tab-vendor", panel: "settings-panel-vendor" },
];
function showSettingsTab(name) {
  for (const tab of SETTINGS_TABS) {
    const active = tab.name === name;
    $(tab.btn).classList.toggle("active", active);
    $(tab.btn).setAttribute("aria-pressed", String(active));
    $(tab.panel).hidden = !active;
  }
  // "นำเข้าราคา" opens a dialog that only makes sense from the vendor tab — shown beside the
  // tabs rather than inside the panel (per request) but still scoped to that one tab.
  $("vendor-import-open").hidden = name !== "vendor";
}
for (const tab of SETTINGS_TABS) {
  $(tab.btn).addEventListener("click", () => showSettingsTab(tab.name));
}

/* ---- theme ---- */
function applyTheme(theme) {
  if (theme === "dark") document.documentElement.setAttribute("data-theme", "dark");
  else document.documentElement.removeAttribute("data-theme");
  try {
    localStorage.setItem("theme", theme);
  } catch (err) {
    /* storage unavailable; the choice just will not survive a reload */
  }
  $("theme-now").textContent = theme === "dark" ? "กำลังใช้ธีมมืด" : "กำลังใช้ธีมสว่าง";
}

/* One row of a settings table: cells is [{tag, text, className}], tag defaults to "td". */
function addRow(host, cells) {
  const row = document.createElement("tr");
  for (const { tag = "td", text, className } of cells) {
    const cell = document.createElement(tag);
    if (className) cell.className = className;
    cell.textContent = text;
    row.append(cell);
  }
  host.append(row);
}

$("theme-dark").addEventListener("click", () => applyTheme("dark"));
$("theme-light").addEventListener("click", () => applyTheme("light"));
applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light");

/* ---- api key ---- */
function showKeyState(isSet) {
  const chip = $("key-state");
  chip.className = isSet ? "chip done" : "chip failed";
  chip.textContent = isSet ? "ตั้ง key ไว้แล้ว" : "ยังไม่ได้ตั้ง key — สร้างภาพไม่ได้";
}

async function loadStatus() {
  const status = await call("/api/settings");
  showKeyState(status.api_key_set);
  $("key-where").textContent = `เก็บไว้ที่ ${status.env_path}`;

  const rows = [
    ["model สร้างภาพ", status.model],
    ["model อ่านรูป", status.vision_model],
    ["ขนาดสินค้า", status.catalog_products ? "โหลดแล้ว" : "ยังไม่มี — รัน scripts/extract_catalog.py"],
    ["ค้นของจากรูป", status.catalog_searchable ? "พร้อมใช้" : "ยังไม่ได้สร้าง — รัน scripts/describe_catalog.py แล้ว embed_catalog.py"],
    ["รหัสชนกัน", status.catalog_conflicts ? `${status.catalog_conflicts} รหัส — ดูรายการด้านล่าง` : "ไม่มี"],
  ];
  const host = $("status-rows");
  host.innerHTML = "";
  for (const [name, value] of rows) {
    addRow(host, [
      { tag: "th", className: "caption", text: name },
      { className: "mono", text: value },
    ]);
  }

  if (status.catalog_conflicts) loadConflicts();
  if (status.catalog_orphans) loadOrphans();
}

async function loadConflicts() {
  const { conflicts } = await call("/api/catalog/conflicts");
  if (!conflicts.length) return;
  $("conflicts-panel").hidden = false;
  const host = $("conflicts-rows");
  host.innerHTML = "";
  for (const item of conflicts) {
    const kept = `${item.kept.section || "(ไม่ระบุหมวด)"} · ${item.kept.size_raw || "ไม่มีขนาด"} · เล่ม ${item.kept.book || "?"} หน้า ${item.kept.page ?? "?"}`;
    const lost = item.lost
      .map(l => `${l.section || "(ไม่ระบุหมวด)"} · ${l.size_raw || "ไม่มีขนาด"} · เล่ม ${l.book || "?"} หน้า ${l.page ?? "?"}`)
      .join(" / ");
    addRow(host, [
      { tag: "th", className: "mono", text: item.code },
      { text: kept },
      { text: lost },
    ]);
  }
}

async function loadOrphans() {
  const { orphans } = await call("/api/catalog/orphans");
  if (!orphans.length) return;
  $("orphans-panel").hidden = false;
  const host = $("orphans-rows");
  host.innerHTML = "";
  for (const item of orphans) {
    const priceText = item.price != null ? `${item.price} บาท` : null;
    const detail = [item.size_raw, priceText, item.section, item.book]
      .filter(Boolean).join(" · ") || "(ไม่มีข้อมูลอื่น)";
    addRow(host, [
      { tag: "th", className: "mono", text: item.code },
      { text: detail },
    ]);
  }
}

$("key-save").addEventListener("click", async () => {
  const input = $("key-input");
  const value = input.value.trim();
  $("key-error").hidden = true;
  if (!value) return;

  $("key-save").disabled = true;
  try {
    const body = new FormData();
    body.append("api_key", value);
    await call("/api/settings/api-key", { method: "POST", body });
    showKeyState(true);
  } catch (err) {
    $("key-error").textContent = err.message;
    $("key-error").hidden = false;
  } finally {
    // cleared whatever happened: a key sitting in a form field is a key on a shared screen
    input.value = "";
    $("key-save").disabled = false;
  }
});

upgradeFilePickers(); // native file inputs say "Choose File" in English; this swaps in a Thai button
loadStatus();

/* ---- catalogue admin: add, or click a row below to edit its fields/photo in place ---- */
let editingCode = null;
let editingPackSize = null; // what the product's pack size was when the form opened (issue #25)

/* Which field name (from the API's "overridden" list) each input shows a "แก้โดยร้านแล้ว"
 * badge for — issue #11: the shop's own opinion, distinguished from the book's value. */
const OVERRIDE_FIELDS = {
  size_raw: "cat-size", section: "cat-section", book: "cat-book", price: "cat-price",
};

function showOverrides(overridden) {
  const active = new Set(overridden || []);
  for (const [field, inputId] of Object.entries(OVERRIDE_FIELDS)) {
    $(`${inputId}-override`).hidden = !active.has(field);
  }
}

function enterEditMode(item) {
  editingCode = item.code;
  $("cat-code").value = item.code;
  $("cat-code").disabled = true;
  $("cat-size").value = item.size_raw || "";
  $("cat-section").value = item.section || "";
  $("cat-book").value = item.book || "";
  $("cat-price").value = item.price ?? "";
  $("cat-pack-size").value = item.pack_size ?? "";
  editingPackSize = item.pack_size ?? null;
  clearFilePicker($("cat-image"));
  $("cat-image-hint").hidden = false;
  $("cat-photo-preview").src = item.image ? catalogImageUrl(item.image) : "";
  $("cat-photo-preview").hidden = !item.image;
  $("cat-photo-override").hidden = !item.has_shop_photo;
  $("cat-add").textContent = "บันทึกการแก้ไข";
  $("cat-form-title").textContent = `แก้ไข ${item.code}`;
  highlightCatalogRow(item.code);
  $("cat-edit-status").hidden = false;
  $("cat-edit-status").textContent = `กำลังแก้ไข ${item.code}`;
  $("cat-edit-cancel").hidden = false;
  showOverrides(item.overridden);
  renderColourGallery(item.code); // async, fire-and-forget — the rest of the form doesn't wait on it
}

function exitEditMode() {
  editingCode = null;
  editingPackSize = null;
  $("cat-code").disabled = false;
  ["cat-code", "cat-size", "cat-section", "cat-book", "cat-price", "cat-pack-size"]
    .forEach((id) => ($(id).value = ""));
  clearFilePicker($("cat-image")); // its filename label has to be reset too, not just the value
  $("cat-image-hint").hidden = true;
  $("cat-photo-preview").hidden = true;
  $("cat-photo-preview").src = "";
  $("cat-photo-override").hidden = true;
  $("cat-add").textContent = "เพิ่มสินค้า";
  $("cat-form-title").textContent = "เพิ่มสินค้าใหม่";
  highlightCatalogRow(null);
  $("cat-edit-status").hidden = true;
  $("cat-edit-cancel").hidden = true;
  showOverrides([]);
  $("cat-colours").hidden = true;
  $("cat-colours").innerHTML = "";
}

/* One colour's thumbnails: the main photo first (issue #17), then every supporting one —
 * "browsing and editing" per AC5, never wired into anything the generator reads. Reuses the
 * accepted-list's own thumb-wrap/thumb-code look rather than inventing a gallery style. */
function colourPhotoThumb(code, image, isMain, onChanged) {
  const wrap = document.createElement("div");
  wrap.className = "thumb-wrap";
  const img = document.createElement("img");
  img.src = catalogImageUrl(image);
  img.className = "checker";
  img.alt = image;
  wrap.append(img);
  if (isMain) {
    const badge = document.createElement("span");
    badge.className = "thumb-code";
    badge.textContent = "หลัก";
    wrap.append(badge);
  }

  const actions = document.createElement("div");
  actions.className = "btn-row";
  if (!isMain) {
    const makeMain = document.createElement("button");
    makeMain.className = "btn";
    makeMain.textContent = "ตั้งเป็นรูปหลัก";
    makeMain.addEventListener("click", async () => {
      $("cat-error").hidden = true;
      try {
        const body = new FormData();
        body.append("image", image);
        await call(`/api/catalog/products/${encodeURIComponent(code)}/main-photo`, {
          method: "POST", body,
        });
        onChanged();
      } catch (err) {
        $("cat-error").textContent = err.message;
        $("cat-error").hidden = false;
      }
    });
    actions.append(makeMain);
  }
  const remove = document.createElement("button");
  remove.className = "btn danger";
  remove.textContent = "ลบ";
  remove.addEventListener("click", async () => {
    $("cat-error").hidden = true;
    try {
      await call(
        `/api/catalog/products/${encodeURIComponent(code)}/photos?image=${encodeURIComponent(image)}`,
        { method: "DELETE" },
      );
      onChanged();
    } catch (err) {
      $("cat-error").textContent = err.message;
      $("cat-error").hidden = false;
    }
  });
  actions.append(remove);

  const cell = document.createElement("div");
  cell.className = "stack";
  cell.append(wrap, actions);
  return cell;
}

async function renderColourGallery(code) {
  const host = $("cat-colours");
  host.innerHTML = "";
  host.hidden = true;
  if (!code) return;

  let colours;
  try {
    ({ colours } = await call(`/api/catalog/products/${encodeURIComponent(code)}/colours`));
  } catch {
    return; // a lookup failure here shouldn't block the rest of the edit form
  }
  if (colours.length <= 1 || code !== editingCode) return; // stale response from a code the shop already navigated away from

  host.hidden = false;
  const title = document.createElement("span");
  title.className = "section-title";
  title.textContent = "รูปแต่ละสี";
  host.append(title);

  for (const colour of colours) {
    const row = document.createElement("div");
    row.className = "stack";
    const label = document.createElement("span");
    label.className = "hint";
    label.textContent = colour.name || colour.image;
    row.append(label);

    const gallery = document.createElement("div");
    gallery.className = "btn-row";
    gallery.append(colourPhotoThumb(code, colour.image, true, () => renderColourGallery(code)));
    for (const supporting of colour.supporting) {
      gallery.append(colourPhotoThumb(code, supporting, false, () => renderColourGallery(code)));
    }
    row.append(gallery);

    const addPhoto = document.createElement("input");
    addPhoto.type = "file";
    addPhoto.className = "input";
    addPhoto.accept = "image/jpeg,image/png";
    addPhoto.addEventListener("change", async () => {
      const file = addPhoto.files[0];
      if (!file) return;
      $("cat-error").hidden = true;
      try {
        const body = new FormData();
        body.append("main_image", colour.image);
        body.append("image", file);
        await call(`/api/catalog/products/${encodeURIComponent(code)}/photos`, {
          method: "POST", body,
        });
        renderColourGallery(code);
      } catch (err) {
        $("cat-error").textContent = err.message;
        $("cat-error").hidden = false;
      }
    });
    row.append(addPhoto);

    host.append(row);
  }
}

$("cat-photo-clear").addEventListener("click", async (event) => {
  event.preventDefault();
  $("cat-error").hidden = true;
  $("cat-photo-clear").style.pointerEvents = "none";
  try {
    const item = await call(`/api/catalog/products/${encodeURIComponent(editingCode)}/photo`, {
      method: "DELETE",
    });
    enterEditMode(item);
    await loadCatalogResults();
  } catch (err) {
    $("cat-error").textContent = err.message;
    $("cat-error").hidden = false;
  } finally {
    $("cat-photo-clear").style.pointerEvents = "";
  }
});

for (const [field, inputId] of Object.entries(OVERRIDE_FIELDS)) {
  const link = $(`${inputId}-clear`);
  link.addEventListener("click", async (event) => {
    event.preventDefault();
    $("cat-error").hidden = true;
    link.style.pointerEvents = "none"; // <a> has no disabled attribute — guard against a double-click firing two clears
    try {
      const body = new FormData();
      body.append("field", field);
      const item = await call(
        `/api/catalog/products/${encodeURIComponent(editingCode)}/clear-override`,
        { method: "POST", body }
      );
      enterEditMode(item);
      await loadCatalogResults();
    } catch (err) {
      $("cat-error").textContent = err.message;
      $("cat-error").hidden = false;
    } finally {
      link.style.pointerEvents = "";
    }
  });
}

$("cat-edit-cancel").addEventListener("click", () => {
  $("cat-error").hidden = true;
  exitEditMode();
});

const CATALOG_PAGE_SIZE = 50;
let catalogPage = 1;
let categoryLabels = {};

function highlightCatalogRow(code) {
  for (const row of $("cat-results").children) {
    row.classList.toggle("selected", row.dataset.code === code);
  }
}

/* What is wrong with a row, in the words the filter offers — the same four things the
 * "กรองตามปัญหา" box narrows to, so a shop scanning the table sees why a product might be
 * missing from the picker without opening it. */
function catalogNote(item) {
  const notes = [];
  if (!item.image) notes.push("ไม่มีรูป");
  else if (item.crop_shared) notes.push("รูปแชร์กับ code อื่น (ซ่อนใน picker)");
  if (!item.size_raw) notes.push("ไม่มีขนาด");
  if (item.price == null) notes.push("ไม่มีราคา");
  return notes.join(" · ");
}

async function loadCatalogResults() {
  const offset = (catalogPage - 1) * CATALOG_PAGE_SIZE;
  const params = new URLSearchParams({
    q: $("cat-search").value.trim(), limit: `${CATALOG_PAGE_SIZE}`, offset: `${offset}`,
  });
  if ($("cat-filter-book").value) params.set("book", $("cat-filter-book").value);
  if ($("cat-filter-category").value) params.set("category", $("cat-filter-category").value);
  if ($("cat-filter-issue").value) params.set("issue", $("cat-filter-issue").value);
  const { results, total } = await call(`/api/catalog/products?${params}`);

  // a reload after an edit can land past the end — snap back to the new last page
  const totalPages = Math.max(1, Math.ceil(total / CATALOG_PAGE_SIZE));
  if (catalogPage > totalPages) {
    catalogPage = totalPages;
    return loadCatalogResults();
  }

  $("cat-results-count").textContent = `(${total})`;
  $("cat-page-info").textContent = `หน้า ${catalogPage} / ${totalPages}`;
  $("cat-page-prev").disabled = catalogPage <= 1;
  $("cat-page-next").disabled = catalogPage >= totalPages;
  $("cat-page-goto").disabled = totalPages <= 1;
  $("cat-page-goto-btn").disabled = totalPages <= 1;
  $("cat-page-goto").max = `${totalPages}`;
  $("cat-page-goto").value = `${catalogPage}`;
  $("cat-page-range").textContent =
    total === 0 ? "" : `แสดงลำดับที่ ${offset + 1}–${offset + results.length} จาก ${total}`;

  const host = $("cat-results");
  host.innerHTML = "";
  results.forEach((item, index) => {
    addRow(host, [
      { className: "mono", text: `${offset + index + 1}` },
      { text: "" }, // photo — filled in below, since addRow only sets textContent
      { className: "mono", text: item.code },
      { className: "hint", text: item.size_raw || "—" },
      { className: "hint", text: categoryLabels[item.category] || "—" },
      { className: "hint", text: item.book || "—" },
      { className: "mono text-right", text: item.price != null ? `${item.price}` : "—" },
      { className: "hint", text: catalogNote(item) },
    ]);
    const row = host.lastElementChild;
    row.className = "cat-recent-row"; // the table's pointer-cursor/hover/selected look
    row.dataset.code = item.code;
    row.addEventListener("click", () => {
      $("cat-error").hidden = true;
      enterEditMode(item);
    });
    const photoCell = row.children[1];
    if (item.image) {
      const img = document.createElement("img");
      img.className = "checker cat-thumb";
      img.src = catalogImageUrl(item.image);
      img.alt = item.code;
      img.loading = "lazy";
      photoCell.append(img);
    } else {
      photoCell.className = "hint";
      photoCell.textContent = "—";
    }
  });
  highlightCatalogRow(editingCode);
}

/* A new search or filter starts back at page 1; paging and reloads after a save keep the page. */
function searchCatalogResults() {
  catalogPage = 1;
  return loadCatalogResults().catch((err) => {
    $("cat-error").textContent = err.message;
    $("cat-error").hidden = false;
  });
}

$("cat-search-btn").addEventListener("click", searchCatalogResults);
$("cat-search").addEventListener("keydown", (event) => {
  if (event.key === "Enter") searchCatalogResults();
});
for (const id of ["cat-filter-book", "cat-filter-category", "cat-filter-issue"]) {
  $(id).addEventListener("change", searchCatalogResults);
}
$("cat-page-prev").addEventListener("click", () => { catalogPage -= 1; loadCatalogResults(); });
$("cat-page-next").addEventListener("click", () => { catalogPage += 1; loadCatalogResults(); });
$("cat-page-goto-btn").addEventListener("click", () => {
  const wanted = Math.floor(Number($("cat-page-goto").value));
  if (wanted >= 1) { catalogPage = wanted; loadCatalogResults(); }
});
$("cat-new").addEventListener("click", () => {
  $("cat-error").hidden = true;
  exitEditMode();
});

/* The shop and category boxes are free text on purpose — a new shop has to be typeable — but
 * both only do their job when they match what the rest of the app already knows, so what
 * exists is offered as a datalist rather than left to memory. */
async function loadCatalogLists() {
  try {
    const [{ shops }, { categories }] = await Promise.all([
      call("/api/catalog/shops"),
      call("/api/catalog/categories"),
    ]);
    const fill = (listId, items) => {
      const list = $(listId);
      list.innerHTML = "";
      for (const item of items) {
        const option = document.createElement("option");
        option.value = item.label;
        list.append(option);
      }
    };
    fill("cat-book-list", shops);
    fill("cat-section-list", categories);
    categoryLabels = Object.fromEntries(categories.map((c) => [c.key, c.label]));
    const fillSelect = (id, allLabel, items, valueOf) => {
      const select = $(id);
      const chosen = select.value;
      select.innerHTML = "";
      select.append(new Option(allLabel, ""));
      for (const item of items) select.append(new Option(`${item.label} (${item.count})`, valueOf(item)));
      select.value = chosen;
    };
    fillSelect("cat-filter-book", "ทุกร้าน", shops, (shop) => shop.key);
    fillSelect("cat-filter-category", "ทุกหมวด", categories, (category) => category.key);
  } catch {
    /* the lists are a convenience; both boxes still accept anything typed into them */
  }
}

/* Says what the two derived fields actually resolved to, because neither fails loudly:
 * an unreadable size just means no exact scale, and a section that matches no category just
 * means the product never shows up under a filter. */
function showSavedState(saved) {
  const parts = [`บันทึก ${saved.code} แล้ว`];
  parts.push(saved.size_mm ? `ขนาด ${Math.round(saved.size_mm)} mm` : "อ่านขนาดไม่ออก");
  if (!saved.category) parts.push("ไม่ตรงหมวดไหน");
  const chip = $("cat-status");
  chip.className = saved.size_mm && saved.category ? "chip done" : "chip stale";
  chip.textContent = parts.join(" · ");
  chip.hidden = false;
}

$("cat-add").addEventListener("click", async () => {
  $("cat-error").hidden = true;
  const image = $("cat-image").files[0];
  if (!editingCode && (!$("cat-code").value.trim() || !image)) {
    $("cat-error").textContent = "ต้องมีรหัสสินค้ากับรูปอย่างน้อย";
    $("cat-error").hidden = false;
    return;
  }

  $("cat-add").disabled = true;
  try {
    const body = new FormData();
    if (!editingCode) body.append("code", $("cat-code").value.trim());
    body.append("size_raw", $("cat-size").value.trim());
    body.append("section", $("cat-section").value.trim());
    body.append("book", $("cat-book").value.trim());
    body.append("price", $("cat-price").value.trim());
    // Adding a brand-new product: the image is its base photo, part of the same request.
    // Editing one: a chosen file is a shop photo (issue #12) and goes through its own
    // endpoint below, since it no longer shares a code path with the book-derived fields.
    if (!editingCode && image) body.append("image", image);

    const url = editingCode
      ? `/api/catalog/products/${encodeURIComponent(editingCode)}`
      : "/api/catalog/products";
    const saved = await call(url, { method: "POST", body });

    if (editingCode && image) {
      const photoBody = new FormData();
      photoBody.append("image", image);
      await call(`/api/catalog/products/${encodeURIComponent(editingCode)}/photo`, {
        method: "POST", body: photoBody,
      });
    }

    // Its own endpoint, like the photo above: a pack size has no book value to be diffed
    // against, so it does not travel with the fields that do (issue #25). Only sent when it
    // actually says something — a blank field on a product that never had one is not an edit,
    // and posting it anyway would write an empty overlay record for every product saved.
    const packSize = $("cat-pack-size").value.trim();
    if (packSize || editingPackSize) {
      const packBody = new FormData();
      packBody.append("pack_size", packSize);
      await call(`/api/catalog/products/${encodeURIComponent(editingCode || saved.code)}/pack-size`, {
        method: "POST", body: packBody,
      });
    }

    if (editingCode) exitEditMode();
    else {
      ["cat-code", "cat-size", "cat-section", "cat-book", "cat-price", "cat-pack-size"]
        .forEach((id) => ($(id).value = ""));
      clearFilePicker($("cat-image"));
    }
    showSavedState(saved);
    await loadCatalogResults();
    await loadCatalogLists();
  } catch (err) {
    $("cat-error").textContent = err.message;
    $("cat-error").hidden = false;
  } finally {
    $("cat-add").disabled = false;
  }
});

$("cat-sync").addEventListener("click", async () => {
  $("cat-error").hidden = true;
  $("cat-sync").disabled = true;
  $("cat-status").hidden = false;
  $("cat-status").className = "chip running";
  $("cat-status").textContent = "กำลัง sync…";
  try {
    await call("/api/catalog/sync", { method: "POST" });
    $("cat-status").className = "chip done";
    $("cat-status").textContent = "sync แล้ว";
  } catch (err) {
    $("cat-status").hidden = true;
    $("cat-error").textContent = err.message;
    $("cat-error").hidden = false;
  } finally {
    $("cat-sync").disabled = false;
  }
});

loadCatalogLists().then(loadCatalogResults);
