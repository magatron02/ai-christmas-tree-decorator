/* Settings — Product.md 8.4.
 *
 * The API key is write-only here as much as on the server: the input is emptied the moment
 * it is sent, nothing ever reads a key back, and the only thing displayed is whether one
 * exists. NonGoals 10 fixed those rules before this page was written. */

const $ = (id) => document.getElementById(id);

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
    const row = document.createElement("tr");
    const key = document.createElement("th");
    key.className = "caption";
    key.textContent = name;
    const detail = document.createElement("td");
    detail.className = "mono";
    detail.textContent = value;
    row.append(key, detail);
    host.append(row);
  }

  if (status.catalog_conflicts) loadConflicts();
}

async function loadConflicts() {
  const { conflicts } = await call("/api/catalog/conflicts");
  if (!conflicts.length) return;
  $("conflicts-panel").hidden = false;
  const host = $("conflicts-rows");
  host.innerHTML = "";
  for (const item of conflicts) {
    const row = document.createElement("tr");

    const code = document.createElement("th");
    code.className = "mono";
    code.textContent = item.code;

    const kept = document.createElement("td");
    kept.textContent = `${item.kept.section || "(ไม่ระบุหมวด)"} · ${item.kept.size_raw || "ไม่มีขนาด"} · เล่ม ${item.kept.book || "?"} หน้า ${item.kept.page ?? "?"}`;

    const lost = document.createElement("td");
    lost.textContent = item.lost
      .map(l => `${l.section || "(ไม่ระบุหมวด)"} · ${l.size_raw || "ไม่มีขนาด"} · เล่ม ${l.book || "?"} หน้า ${l.page ?? "?"}`)
      .join(" / ");

    row.append(code, kept, lost);
    host.append(row);
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

loadStatus();

/* ---- catalogue admin: add, or click a row below to edit its fields/photo in place ---- */
let editingCode = null;

function enterEditMode(item) {
  editingCode = item.code;
  $("cat-code").value = item.code;
  $("cat-code").disabled = true;
  $("cat-size").value = item.size_raw || "";
  $("cat-section").value = item.section || "";
  $("cat-book").value = item.book || "";
  $("cat-price").value = item.price ?? "";
  $("cat-image").value = "";
  $("cat-image-hint").hidden = false;
  $("cat-add").textContent = "บันทึกการแก้ไข";
  $("cat-edit-status").hidden = false;
  $("cat-edit-status").textContent = `กำลังแก้ไข ${item.code}`;
  $("cat-edit-cancel").hidden = false;
}

function exitEditMode() {
  editingCode = null;
  $("cat-code").disabled = false;
  ["cat-code", "cat-size", "cat-section", "cat-book", "cat-price", "cat-image"].forEach((id) => ($(id).value = ""));
  $("cat-image-hint").hidden = true;
  $("cat-add").textContent = "เพิ่มสินค้า";
  $("cat-edit-status").hidden = true;
  $("cat-edit-cancel").hidden = true;
}

$("cat-edit-cancel").addEventListener("click", () => {
  $("cat-error").hidden = true;
  exitEditMode();
});

async function loadRecentCatalog() {
  const { results } = await call("/api/catalog/recent");
  const host = $("cat-recent");
  host.innerHTML = "";
  for (const item of results) {
    const row = document.createElement("tr");
    row.className = "cat-recent-row";
    const photo = document.createElement("td");
    if (item.image) {
      const img = document.createElement("img");
      img.src = `/catalog/${item.image}`;
      img.alt = item.code;
      img.className = "checker cat-thumb";
      photo.append(img);
    }
    const code = document.createElement("td");
    code.className = "mono";
    code.textContent = item.code;
    const meta = document.createElement("td");
    meta.className = "hint";
    const priceText = item.price != null ? `${item.price} บาท` : null;
    meta.textContent = [item.size_raw, priceText, item.book].filter(Boolean).join(" · ");
    row.append(photo, code, meta);
    row.addEventListener("click", () => enterEditMode(item));
    host.append(row);
  }
}

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
    if (image) body.append("image", image);

    const url = editingCode
      ? `/api/catalog/products/${encodeURIComponent(editingCode)}`
      : "/api/catalog/products";
    const saved = await call(url, { method: "POST", body });

    if (editingCode) exitEditMode();
    else ["cat-code", "cat-size", "cat-section", "cat-book", "cat-price", "cat-image"].forEach((id) => ($(id).value = ""));
    showSavedState(saved);
    await loadRecentCatalog();
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

loadRecentCatalog();
loadCatalogLists();
