/* The one place page state lives (SPEC layout v2 §3). Loaded before every other script.
 *
 * Every mode reads and writes this object — nothing keeps a parallel copy. Switching mode
 * changes `mode` and nothing else, so the base photo, decorations, atmosphere reference and
 * output settings survive it. `setStore()` is the write path for anything that changes what is
 * on screen; `render()` (render.js) is the only thing that turns the store into DOM.
 *
 * Fields a person is typing into (a size in mm, the prompt text) are written directly and
 * followed by renderFooter() instead — a full render would rebuild the very input being typed in.
 */
window.store = {
  mode: "custom",            // "custom" | "prompt" | "auto"
  backdrop: "tree",          // "tree" | "wall" — what the base photo is, and what Auto/the picker fill for

  // The tree (or wall) photo. null until one is chosen.
  //   {type, file, url, code, sizeMm, manualMm, price, typedPrice, ratio}
  //   code: set only by the catalogue picker — an uploaded photo has no code.
  //   sizeMm: the code's catalogue size, or null if it has none (the blocking size gate).
  //   manualMm: person-typed override when sizeMm is null.
  //   price: null = the book never printed one (issue #27); typedPrice: one typed and saved.
  //   ratio: width/height of the photo.
  base: null,

  // One entry per decoration, up to limits.maxElements:
  //   {name, url, code, image, colours, sizeMm, manualMm, price, typedPrice, density, status}
  //   name is the server's stored cut-out filename (what /api/prepare's "element" wants).
  //   image: the catalogue colour photo it came from (null for an upload); colours: that
  //   product's other colours, null unless it has more than one (issue #15).
  //   status: "ready" | "pending" (uploaded, waiting for a manual cut) | "cutting" | "failed".
  decorations: [],

  atmosphereRef: null,       // {name, url, ratio} — the optional scene photo, `name` as the server stored it
  output: { ratio: "4:5", density: "normal" },   // DENSITY_PRESETS key; ratio is a size preset key or "auto"
  prompt: "",                // Prompt mode's free text
  tone: null,                // Auto mode's chosen tone key

  result: null,              // the last /api/generate response (or a request resumed from history)
  status: "idle",            // pipeline state shown in the footer chip
  busy: false,               // a request is being prepared or generated — locks the sidebar

  run: {
    requestId: null,
    quantities: null,        // prepared.quantities from the last /api/prepare, indexed like decorations
    // code -> exact count from the last "นับของในรูปนี้" click, or null before it is pressed (or
    // after anything about the tree/decorations changes and invalidates it — see resetRun).
    counted: null,
  },

  auto: {
    loaded: null,            // which backdrop `config` was fetched for, null before the first fetch
    config: null,
    pick: null,              // last /api/auto/pick response
    pickError: null,
    exclude: [],             // codes already shown, so "สุ่มใหม่" avoids repeats where stock allows
    preparing: false,        // the pick is being turned into cut-out files
  },

  config: { sizes: [], densities: [] },      // /api/config
  limits: { maxElements: 10, promptMaxChars: 500 },

  ui: {
    autoCut: true,           // "ตัดพื้นหลังอัตโนมัติ" on the upload zone
    samples: false,          // the base step's sample strip is open
    atmosphereOpen: false,   // the atmosphere step is expanded
    sceneSamples: false,
    stageView: "original",   // "original" | "result"
  },
};

function setStore(patch) {
  Object.assign(window.store, patch);
  render();
}
