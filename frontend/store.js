/* The one place page state lives (SPEC-layout-v2 §3). Loaded before every other script.
 *
 * Each mode keeps its own slice; app.js, auto.js and prompt.js alias their slice
 * (`const state = store.custom`) so they still read and write the same object they always did
 * — moving the objects here changed no field and no behaviour, which the ?dryrun=1 payload
 * snapshots in tests/payload-before/ check.
 */
window.store = {
  // "กำหนดเอง" — also where Auto's picks land before the shop reviews them
  custom: {
    treeFile: null,
    treeCode: null, // set only by the catalogue picker — an uploaded photo has no code
    treeSizeMm: null, // the tree code's catalogue size, or null if it has none (blocking gate)
    treeManualMm: null, // person-typed override when treeSizeMm is null
    treePrice: null, // the tree code's price, null = the book never printed one (issue #27)
    treeTypedPrice: null, // one typed into that offer and saved — shown back, never a gate
    // {name, url, code, image, colours, sizeMm, manualMm, price, density} — one entry per accepted
    // cut-out, up to MAX_ELEMENTS. sizeMm is the code's catalogue size (null = none, blocking
    // gate); manualMm is a person-typed override; price is the code's price (null = unpriced,
    // an offer to fill it in, never a gate) and typedPrice one filled into that offer;
    // density is a DENSITY_PRESETS key, per item.
    // image is the catalogue colour photo this cutout came from (null for an uploaded photo);
    // colours is that product's other colours (issue #15), fetched once at accept time — null
    // unless the product actually has more than one, which is also the "offer a switcher" flag.
    elements: [],
    sceneReference: null, // stored filename of the optional scene/ambience photo (used at generate time)
    requestId: null,
    busy: false,
    quantities: null, // prepared.quantities from the last /api/prepare, indexed like state.elements
    treeRatio: null, // width/height of whatever photo is in the tree slot right now
    sceneRatio: null, // width/height of the scene reference, when one is set
    // code -> exact count from the last "นับของในรูปนี้" click, or null before that button is
    // pressed (or after anything about the tree/decorations changes and invalidates it — see
    // resetRun). Only used to redraw #result-quantities here — the full price breakdown lives
    // on its own page now (quote.html/quote.js), reached via #quote-link once generated.
    counted: null,
  },

  prompt: {
    attachments: [], // {role: "tree"|"element"|"scene", file, url, code, sizeMm, manualMm}
    maxChars: 500,   // overwritten by /api/config's prompt_mode_max_chars once it loads
    sending: false,
  },

  auto: {
    loaded: null,    // which backdrop `config` was fetched for, null before the first fetch
    config: null,
    tone: null,
    pick: null,      // last /api/auto/pick response
    pickError: null,
    exclude: [],     // codes already shown, so "สุ่มใหม่" avoids repeats where stock allows
  },
};
