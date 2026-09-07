/* Pricing queue — issue #10. Fast entry: photo, code, one price field, next. */

const $ = (id) => document.getElementById(id);

let currentCode = null;

async function loadNext() {
  $("queue-error").hidden = true;
  const { remaining, next } = await call("/api/catalog/pricing-queue");
  $("queue-remaining").textContent = `เหลือ ${remaining} ชิ้น`;

  if (!next) {
    currentCode = null;
    $("queue-item").hidden = true;
    $("queue-done").hidden = false;
    return;
  }

  $("queue-done").hidden = true;
  $("queue-item").hidden = false;
  currentCode = next.code;
  $("queue-code").textContent = next.code;
  $("queue-meta").textContent = [next.size_raw, next.section, next.book].filter(Boolean).join(" · ");
  $("queue-photo").src = next.image ? `/catalog/${next.image}` : "";
  $("queue-photo").hidden = !next.image;
  $("queue-price").value = "";
  $("queue-price").focus();
}

$("queue-save").addEventListener("click", async () => {
  const price = $("queue-price").value.trim();
  if (!price) {
    $("queue-error").textContent = "ใส่ราคาก่อน — ถ้าจะไม่ตั้งราคาให้กด \"ข้ามถาวร\" แทน";
    $("queue-error").hidden = false;
    return;
  }

  $("queue-save").disabled = true;
  try {
    const body = new FormData();
    body.append("price", price);
    await call(`/api/catalog/pricing-queue/${encodeURIComponent(currentCode)}/price`, {
      method: "POST", body,
    });
    await loadNext();
  } catch (err) {
    $("queue-error").textContent = err.message;
    $("queue-error").hidden = false;
  } finally {
    $("queue-save").disabled = false;
  }
});

$("queue-price").addEventListener("keydown", (event) => {
  if (event.key === "Enter") $("queue-save").click();
});

$("queue-skip").addEventListener("click", async () => {
  $("queue-error").hidden = true;
  $("queue-skip").disabled = true;
  try {
    await call(`/api/catalog/pricing-queue/${encodeURIComponent(currentCode)}/skip`, {
      method: "POST",
    });
    await loadNext();
  } catch (err) {
    $("queue-error").textContent = err.message;
    $("queue-error").hidden = false;
  } finally {
    $("queue-skip").disabled = false;
  }
});

loadNext();
