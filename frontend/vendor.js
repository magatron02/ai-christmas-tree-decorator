/* Vendor price-list admin (settings page) — browse, fix, import.
 *
 * Corrections go to data/vendor_overlay.json, a second base+overlay split parallel to the
 * catalogue's own (ADR-0001) — see backend/services/vendor_overlay.py. This file mirrors
 * settings.js's own conventions (the shared `call()` helper, addRow-style rows, a "แก้โดยร้าน
 * แล้ว" chip + "ล้างกลับ" link per overridable field) rather than inventing new ones.
 *
 * "Check for errors" is not a separate screen here — backend/services/vendor_admin.py computes
 * a per-row "หมายเหตุ" (missing price/size, an unresolved pack) that shows right in the browse
 * table and the edit panel, so a problem surfaces where the code already is instead of a second
 * list to cross-reference. GET /api/vendor/issues still exists for the categorised view (a
 * catalogued code with literally no vendor row can't appear as a row here to carry a remark),
 * just nothing in this UI calls it. */

let vendorEditingCode = null;
let vendorOriginalValues = {}; // field -> value shown when editing started, for the save
                                // handler's diff (see VENDOR_TEXT_FIELDS below)
let vendorPage = 1; // 1-based; reset to 1 by a new search, kept as-is by an in-place reload
const VENDOR_PAGE_SIZE = 50;

/* Every configured supplier, for the browse filter and the import dialog's picker — same
 * "fetch once, fill every select that needs it" approach as settings.js's loadCatalogLists(). */
async function loadVendorSuppliers() {
  const { suppliers } = await call("/api/vendor/suppliers");

  const importSelect = $("vendor-import-supplier");
  importSelect.innerHTML = "";
  for (const { key, label } of suppliers) {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = label;
    importSelect.append(option);
  }

  const filterSelect = $("vendor-search-supplier");
  for (const { key, label } of suppliers) {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = label;
    filterSelect.append(option);
  }
}

/* Plain text/number fields, saved one at a time by the loop in the save handler below. */
const VENDOR_TEXT_FIELDS = {
  price: "vendor-price", size_mm: "vendor-size_mm", name: "vendor-name",
  pack_qty: "vendor-pack_qty", pack_unit: "vendor-pack_unit",
};

/* The override chip/clear-link shown per group — pack_qty and pack_unit share one ("แพ็ค"
 * is one visible pair, edited and cleared together), everything else is 1:1 with a backend
 * overlay field. Keys are the DOM id fragment (vendor-<key>-override/-clear); values are the
 * backend field name(s) that group actually speaks for. pack_ambiguous is a checkbox, not a
 * text field, but gets the same chip/clear treatment as everything else. */
const VENDOR_OVERRIDE_GROUPS = {
  price: ["price"], size_mm: ["size_mm"], name: ["name"],
  pack_qty: ["pack_qty", "pack_unit"], pack_ambiguous: ["pack_ambiguous"],
};

function showVendorOverrides(overridden) {
  const active = new Set(overridden || []);
  for (const [key, fields] of Object.entries(VENDOR_OVERRIDE_GROUPS)) {
    $(`vendor-${key}-override`).hidden = !fields.some((field) => active.has(field));
  }
}

/* Marks which row (by data-code, set when the table is built below) is the one currently
 * open in the edit panel — reruns on every table render too, since re-rendering after a save
 * loses whatever classes the old row elements had. */
function highlightVendorRow(code) {
  for (const row of $("vendor-results").children) {
    row.classList.toggle("selected", code != null && row.dataset.code === code);
  }
}

function enterVendorEdit(item) {
  vendorEditingCode = item.code;
  highlightVendorRow(item.code);
  $("vendor-edit-empty").hidden = true;
  $("vendor-edit-status").textContent = `กำลังแก้ไข ${item.code}`;
  $("vendor-edit-note").textContent = item.note || "";
  $("vendor-edit-note").hidden = !item.note;
  $("vendor-price").value = item.price ?? "";
  $("vendor-size_mm").value = item.size_mm ?? "";
  $("vendor-name").value = item.name ?? "";
  const pack = item.pack || {};
  $("vendor-pack_qty").value = pack.qty ?? "";
  $("vendor-pack_unit").value = pack.qty != null ? (pack.unit ?? "") : "";
  $("vendor-pack_ambiguous").checked = false;
  showVendorOverrides(item.overridden);
  $("vendor-error").hidden = true;
  $("vendor-edit").hidden = false;

  // Snapshot what's now shown, so "บันทึก" only sends fields the shop actually retyped —
  // without this, every non-blank field (the whole form, since it's pre-filled from `item`)
  // got resubmitted on every save, quietly claiming an opinion on fields nobody touched.
  vendorOriginalValues = {};
  for (const [field, inputId] of Object.entries(VENDOR_TEXT_FIELDS)) {
    vendorOriginalValues[field] = $(inputId).value.trim();
  }
}

function exitVendorEdit() {
  vendorEditingCode = null;
  vendorOriginalValues = {};
  highlightVendorRow(null);
  $("vendor-edit").hidden = true;
  $("vendor-edit-empty").hidden = false;
  for (const id of Object.values(VENDOR_TEXT_FIELDS)) $(id).value = "";
  $("vendor-pack_ambiguous").checked = false;
  showVendorOverrides([]);
}

/* "จำนวน" column text — same {qty, unit}/{ambiguous}/null shape vendor_lookup.pack_for()
 * returns, backend/main.py rounds the quantity needed up to whole packs of by. */
function vendorPackText(pack) {
  if (!pack) return "1 ชิ้น"; // vendor_lookup.pack_for(): None means plainly per-piece, not unknown
  if (pack.ambiguous) return "ไม่ชัดเจน";
  return `${pack.qty} ชิ้น/${pack.unit}`;
}

async function loadVendorResults(query) {
  const supplier = $("vendor-search-supplier").value;
  const catalogFilter = $("vendor-search-catalog").value;
  const sizeFilter = $("vendor-search-size").value;
  const nameFilter = $("vendor-search-name").value;
  const offset = (vendorPage - 1) * VENDOR_PAGE_SIZE;
  const params = new URLSearchParams({ q: query || "", limit: `${VENDOR_PAGE_SIZE}`, offset: `${offset}` });
  if (supplier) params.set("supplier", supplier);
  if (catalogFilter) params.set("in_catalog", catalogFilter);
  if (sizeFilter === "missing") params.set("missing_size", "true");
  if (nameFilter === "unmapped") params.set("unmapped_char", "true");
  const { results, total } = await call(`/api/vendor/products?${params}`);

  // A reload after an edit/import can land past the end (e.g. the last item on the last page
  // just got its only match filtered out) — snap back to the new last page instead of showing
  // an empty one.
  const totalPages = Math.max(1, Math.ceil(total / VENDOR_PAGE_SIZE));
  if (vendorPage > totalPages) {
    vendorPage = totalPages;
    return loadVendorResults(query);
  }

  $("vendor-results-count").textContent = `(${total})`;
  $("vendor-page-info").textContent = `หน้า ${vendorPage} / ${totalPages}`;
  $("vendor-page-prev").disabled = vendorPage <= 1;
  $("vendor-page-next").disabled = vendorPage >= totalPages;
  $("vendor-page-goto").disabled = totalPages <= 1;
  $("vendor-page-goto-btn").disabled = totalPages <= 1;
  $("vendor-page-goto").max = `${totalPages}`;
  $("vendor-page-goto").value = `${vendorPage}`;
  $("vendor-page-range").textContent =
    total === 0 ? "" : `แสดงลำดับที่ ${offset + 1}–${offset + results.length} จาก ${total}`;

  const host = $("vendor-results");
  host.innerHTML = "";
  results.forEach((item, index) => {
    addRow(host, [
      { className: "mono", text: `${offset + index + 1}` },
      { className: "mono", text: item.code },
      { text: item.name || "(ไม่มีชื่อ)" },
      { className: "hint", text: vendorPackText(item.pack) },
      { className: "mono text-right", text: item.price != null ? `${item.price}` : "—" },
      { className: "mono text-right", text: item.size_mm != null ? `${item.size_mm}` : "—" },
      { text: "" }, // catalog badge — addRow only sets textContent, filled in as a chip below
      { className: "hint", text: item.note },
    ]);
    const row = host.lastElementChild;
    row.className = "cat-recent-row"; // reuse the catalogue table's pointer-cursor/hover look
    row.dataset.code = item.code;
    row.addEventListener("click", () => enterVendorEdit(item));

    const catalogCell = row.children[6];
    catalogCell.className = "hint";
    catalogCell.style.textAlign = "center";
    catalogCell.textContent = item.in_catalog ? "มี" : "—";
  });
  highlightVendorRow(vendorEditingCode); // reapply — the rows above are freshly built
}

/* A new search/filter always starts back at page 1; paging and in-place reloads (after an
 * edit, an override clear, an import) keep whatever page the shop was already looking at. */
function searchVendorResults() {
  vendorPage = 1;
  loadVendorResults($("vendor-search").value.trim());
}

$("vendor-search-btn").addEventListener("click", searchVendorResults);
$("vendor-search").addEventListener("keydown", (event) => {
  if (event.key === "Enter") searchVendorResults();
});
$("vendor-search-supplier").addEventListener("change", searchVendorResults);
$("vendor-search-catalog").addEventListener("change", searchVendorResults);
$("vendor-search-size").addEventListener("change", searchVendorResults);
$("vendor-search-name").addEventListener("change", searchVendorResults);

$("vendor-page-prev").addEventListener("click", () => {
  if (vendorPage <= 1) return;
  vendorPage -= 1;
  loadVendorResults($("vendor-search").value.trim());
});
$("vendor-page-next").addEventListener("click", () => {
  vendorPage += 1;
  loadVendorResults($("vendor-search").value.trim());
});

function goToVendorPage() {
  const wanted = parseInt($("vendor-page-goto").value, 10);
  const max = parseInt($("vendor-page-goto").max, 10) || 1;
  if (!wanted || wanted < 1 || wanted > max) return;
  vendorPage = wanted;
  loadVendorResults($("vendor-search").value.trim());
}
$("vendor-page-goto-btn").addEventListener("click", goToVendorPage);
$("vendor-page-goto").addEventListener("keydown", (event) => {
  if (event.key === "Enter") goToVendorPage();
});

async function clearVendorField(field) {
  const body = new FormData();
  body.append("field", field);
  return call(
    `/api/vendor/products/${encodeURIComponent(vendorEditingCode)}/clear-override`,
    { method: "POST", body },
  );
}

for (const [key, fields] of Object.entries(VENDOR_OVERRIDE_GROUPS)) {
  $(`vendor-${key}-clear`).addEventListener("click", async (event) => {
    event.preventDefault();
    const link = event.currentTarget;
    $("vendor-error").hidden = true;
    link.style.pointerEvents = "none";
    try {
      let item;
      for (const field of fields) item = await clearVendorField(field);
      enterVendorEdit(item);
      await loadVendorResults($("vendor-search").value.trim());
    } catch (err) {
      $("vendor-error").textContent = err.message;
      $("vendor-error").hidden = false;
    } finally {
      link.style.pointerEvents = "";
    }
  });
}

$("vendor-edit-cancel").addEventListener("click", () => {
  $("vendor-error").hidden = true;
  exitVendorEdit();
});

async function setVendorField(field, value) {
  const body = new FormData();
  body.append("field", field);
  body.append("value", value);
  await call(`/api/vendor/products/${encodeURIComponent(vendorEditingCode)}`, {
    method: "POST", body,
  });
}

$("vendor-save").addEventListener("click", async () => {
  $("vendor-error").hidden = true;
  const qty = $("vendor-pack_qty").value.trim();
  const unit = $("vendor-pack_unit").value.trim();
  if (Boolean(qty) !== Boolean(unit)) {
    $("vendor-error").textContent = "จำนวนต่อแพ็คกับหน่วยแพ็ค ต้องใส่คู่กันทั้งสองช่อง";
    $("vendor-error").hidden = false;
    return;
  }

  $("vendor-save").disabled = true;
  try {
    // Only fields that actually changed from what was shown when editing started are sent —
    // this button only ever sets an opinion, never clears one, so a blank box stays untouched
    // (settings.js's catalogue form sidesteps the same "does blank mean no-opinion or an
    // opinion of nothing" question the same way, one field at a time); but every OTHER field
    // is pre-filled from the current record too, and re-submitting an unedited value used to
    // claim a fresh opinion on it regardless — the whole form, on every save, not just what
    // was actually retyped. Diffing against enterVendorEdit()'s own snapshot fixes that.
    for (const [field, inputId] of Object.entries(VENDOR_TEXT_FIELDS)) {
      const value = $(inputId).value.trim();
      if (value && value !== vendorOriginalValues[field]) await setVendorField(field, value);
    }
    if ($("vendor-pack_ambiguous").checked) await setVendorField("pack_ambiguous", "true");

    const item = await call(`/api/vendor/products/${encodeURIComponent(vendorEditingCode)}`);
    enterVendorEdit(item);
    await loadVendorResults($("vendor-search").value.trim());
  } catch (err) {
    $("vendor-error").textContent = err.message;
    $("vendor-error").hidden = false;
  } finally {
    $("vendor-save").disabled = false;
  }
});

/* ---- import (dialog, opened from the button beside the tabs) ---- */

$("vendor-import-open").addEventListener("click", () => {
  $("vendor-import-file").value = "";
  $("vendor-import-status").hidden = true;
  $("vendor-import-error").hidden = true;
  $("vendor-import-dialog").showModal();
});
$("vendor-import-close").addEventListener("click", () => $("vendor-import-dialog").close());

$("vendor-import-btn").addEventListener("click", async () => {
  const file = $("vendor-import-file").files[0];
  const supplier = $("vendor-import-supplier").value;
  $("vendor-import-error").hidden = true;
  if (!supplier) {
    $("vendor-import-error").textContent = "เลือกซัพพลายเออร์ก่อน";
    $("vendor-import-error").hidden = false;
    return;
  }
  if (!file) {
    $("vendor-import-error").textContent = "เลือกไฟล์ PDF ก่อน";
    $("vendor-import-error").hidden = false;
    return;
  }

  $("vendor-import-btn").disabled = true;
  $("vendor-import-status").hidden = false;
  $("vendor-import-status").className = "chip running";
  $("vendor-import-status").textContent = "กำลังนำเข้า… อาจใช้เวลาสักครู่";
  try {
    const body = new FormData();
    body.append("supplier", supplier);
    body.append("pdf", file);
    const result = await call("/api/vendor/import", { method: "POST", body });
    $("vendor-import-status").className = "chip done";
    $("vendor-import-status").textContent =
      `นำเข้าแล้ว — เพิ่ม ${result.added}, แก้ไข ${result.changed}, หาย ${result.removed} ` +
      `(รวม ${result.total_codes} รหัส)`;
    $("vendor-import-file").value = "";
    await loadVendorResults($("vendor-search").value.trim());
  } catch (err) {
    $("vendor-import-status").hidden = true;
    $("vendor-import-error").textContent = err.message;
    $("vendor-import-error").hidden = false;
  } finally {
    $("vendor-import-btn").disabled = false;
  }
});

loadVendorSuppliers().then(() => loadVendorResults(""));
