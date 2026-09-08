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
