/* Shared fetch wrapper for every page — throws with a Thai message on both a network failure
 * and a non-2xx response, so no page has to hand-roll its own fetch/parse/throw dance. */

async function call(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error("เชื่อมต่อ server ไม่ได้ — เช็คว่า server ยังรันอยู่ไหม");
  }
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    /* a non-JSON body means the server fell over; the status line still tells us enough */
  }
  if (!response.ok) throw new Error(payload.error || `${response.status} ${response.statusText}`);
  return payload;
}

/* A catalogue `image` value is either a bare book-crop filename (served under /catalog/) or,
 * once a shop has photographed the product itself, an absolute URL already rooted at "/"
 * (served under /shop-photos/ — issue #12). Every page that draws a catalogue picture goes
 * through this rather than hardcoding the /catalog/ prefix, so a shop photo just works. */
function catalogImageUrl(image) {
  return image.startsWith("/") ? image : `/catalog/${image}`;
}

/* The native file input paints its own "Choose File / No file chosen" — the browser's words,
 * in the browser's language, and no attribute or stylesheet changes them. On a page that is
 * Thai everywhere else that reads as a hole, so every visible file input here is hidden behind
 * a real button that opens it, with the chosen filename shown beside it.
 *
 * Runs over the whole page at load, so a new upload field needs no wiring of its own: give it
 * `class="input" type="file"` like the others and it is upgraded with them. Prompt mode's
 * inputs already have their own attach buttons and are marked `hidden`, so they are skipped. */
const NO_FILE_TEXT = "ยังไม่ได้เลือกรูป";

function upgradeFilePickers(label = "เลือกรูป") {
  for (const input of document.querySelectorAll('input.input[type="file"]:not([hidden])')) {
    const row = document.createElement("div");
    row.className = "file-picker";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn";
    button.textContent = label;
    const name = document.createElement("span");
    name.className = "hint file-picker-name";
    name.textContent = NO_FILE_TEXT;

    button.addEventListener("click", () => input.click());
    input.addEventListener("change", () => {
      name.textContent = input.files[0] ? input.files[0].name : NO_FILE_TEXT;
    });

    input.hidden = true;
    input.classList.remove("input"); // the button is the visible control now
    row.append(button, name);
    input.parentNode.insertBefore(row, input);
    input.pickerName = name; // clearFilePicker's handle onto the label it has to reset
  }
}

/* Clearing a file input from script fires no `change`, so the filename beside it has to be told
 * separately — call this instead of setting `.value = ""` on an upgraded input. */
function clearFilePicker(input) {
  input.value = "";
  if (input.pickerName) input.pickerName.textContent = NO_FILE_TEXT;
}

/* "16–26" for a range, "16" when both ends agree — every count in this app comes from an
 * estimate with two ends, and a range reading "16–16" looks like a bug rather than a
 * certainty. */
function rangeText(low, high) {
  return low === high ? `${low}` : `${low}–${high}`;
}

/* "2–3 แพ็ค (แพ็คละ 10)" for a product sold by the box, or "" for one sold by the piece
 * (issue #25). One phrasing shared by the result panel and the history table, so the two
 * cannot drift into saying the same thing two ways. */
function packPhrase(packs) {
  return packs ? `${rangeText(packs.low, packs.high)} แพ็ค (แพ็คละ ${packs.pack_size})` : "";
}
