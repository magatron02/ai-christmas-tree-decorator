/* Settings — Product.md 8.4.
 *
 * The API key is write-only here as much as on the server: the input is emptied the moment
 * it is sent, nothing ever reads a key back, and the only thing displayed is whether one
 * exists. NonGoals 10 fixed those rules before this page was written. */

const $ = (id) => document.getElementById(id);

/* ---- theme ---- */
function applyTheme(theme) {
  if (theme === "light") document.documentElement.setAttribute("data-theme", "light");
  else document.documentElement.removeAttribute("data-theme");
  try {
    localStorage.setItem("theme", theme);
  } catch (err) {
    /* storage unavailable; the choice just will not survive a reload */
  }
  $("theme-now").textContent = theme === "light" ? "Light is on." : "Dark is on.";
}

$("theme-dark").addEventListener("click", () => applyTheme("dark"));
$("theme-light").addEventListener("click", () => applyTheme("light"));
applyTheme(document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark");

/* ---- api key ---- */
function showKeyState(isSet) {
  const chip = $("key-state");
  chip.className = isSet ? "chip done" : "chip failed";
  chip.textContent = isSet ? "A key is set" : "No key set — nothing can be generated";
}

async function loadStatus() {
  const response = await fetch("/api/settings");
  const status = await response.json();
  showKeyState(status.api_key_set);
  $("key-where").textContent = `Stored in ${status.env_path}`;

  const rows = [
    ["Image model", status.model],
    ["Vision model", status.vision_model],
    ["Product sizes", status.catalog_products ? "loaded" : "missing — run scripts/extract_catalog.py"],
    ["Reference matching", status.catalog_searchable ? "ready" : "not built — run scripts/describe_catalog.py then embed_catalog.py"],
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
