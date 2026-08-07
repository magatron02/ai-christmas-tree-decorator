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
