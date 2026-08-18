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
