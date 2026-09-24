/* Stage view switching (SPEC layout v2 §5): which of "ต้นฉบับ" / "ผลลัพธ์" the stage shows.
 *
 * Nothing here is told about a new tree or a finished generation. It watches the two elements
 * app.js already reveals — the tree preview frame and the result image — and follows them, so
 * no call site in app.js/prompt.js had to change to drive the stage.
 */
const STAGE_VIEWS = { original: "stage-view-original", result: "stage-view-result" };

function showStageView(name) {
  for (const [view, panel] of Object.entries(STAGE_VIEWS)) {
    const active = view === name;
    $(`stage-tab-${view}`).classList.toggle("active", active);
    $(`stage-tab-${view}`).setAttribute("aria-pressed", String(active));
    $(panel).hidden = !active;
  }
}
$("stage-tab-original").addEventListener("click", () => showStageView("original"));
$("stage-tab-result").addEventListener("click", () => showStageView("result"));

new MutationObserver(() => { if (!$("out-result").hidden) showStageView("result"); })
  .observe($("out-result"), { attributes: true, attributeFilter: ["hidden"] });
new MutationObserver(() => { if (!$("tree-preview-frame").hidden) showStageView("original"); })
  .observe($("tree-preview-frame"), { attributes: true, attributeFilter: ["hidden"] });
