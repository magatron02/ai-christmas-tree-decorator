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
  const response = await fetch("/api/settings");
  const status = await response.json();
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
  const { conflicts } = await (await fetch("/api/catalog/conflicts")).json();
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
    const response = await fetch("/api/settings/api-key", { method: "POST", body });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || response.statusText);
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

/* ---- catalogue admin: add only, no edit/delete ---- */
async function loadRecentCatalog() {
  const response = await fetch("/api/catalog/recent");
  const { results } = await response.json();
  const host = $("cat-recent");
  host.innerHTML = "";
  for (const item of results) {
    const row = document.createElement("tr");
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
    meta.textContent = [item.size_raw, item.book].filter(Boolean).join(" · ");
    row.append(photo, code, meta);
    host.append(row);
  }
}

$("cat-add").addEventListener("click", async () => {
  $("cat-error").hidden = true;
  const image = $("cat-image").files[0];
  if (!$("cat-code").value.trim() || !image) {
    $("cat-error").textContent = "ต้องมีรหัสสินค้ากับรูปอย่างน้อย";
    $("cat-error").hidden = false;
    return;
  }
  $("cat-add").disabled = true;
  try {
    const body = new FormData();
    body.append("code", $("cat-code").value.trim());
    body.append("size_raw", $("cat-size").value.trim());
    body.append("section", $("cat-section").value.trim());
    body.append("book", $("cat-book").value.trim());
    body.append("image", image);
    const response = await fetch("/api/catalog/products", { method: "POST", body });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || response.statusText);
    ["cat-code", "cat-size", "cat-section", "cat-book", "cat-image"].forEach((id) => ($(id).value = ""));
    await loadRecentCatalog();
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
    const response = await fetch("/api/catalog/sync", { method: "POST" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || response.statusText);
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
