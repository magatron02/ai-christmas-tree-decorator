/* Collapses the left nav to icons only, to give the panels more width — a shop running this
 * on a laptop screen loses real width to five spelled-out nav labels it already knows by icon.
 *
 * Same "apply before paint" pattern as theme.js: read the saved state here, in <head>, so the
 * sidebar never flashes wide then narrow on load. The click handler waits for DOMContentLoaded
 * since the toggle button itself hasn't parsed yet at this point in <head>.
 */
(function () {
  var collapsed = false;
  try {
    collapsed = localStorage.getItem("sidebarCollapsed") === "1";
  } catch (err) {
    /* private browsing or storage disabled — expanded is the default and that is fine */
  }
  if (collapsed) document.documentElement.setAttribute("data-sidebar", "collapsed");
})();

document.addEventListener("DOMContentLoaded", function () {
  var toggle = document.getElementById("sidebar-toggle");
  if (!toggle) return;

  function applyLabel() {
    var isCollapsed = document.documentElement.getAttribute("data-sidebar") === "collapsed";
    toggle.title = isCollapsed ? "ขยายเมนู" : "ย่อเมนู";
  }
  applyLabel();

  toggle.addEventListener("click", function () {
    var wasCollapsed = document.documentElement.getAttribute("data-sidebar") === "collapsed";
    if (wasCollapsed) document.documentElement.removeAttribute("data-sidebar");
    else document.documentElement.setAttribute("data-sidebar", "collapsed");
    try {
      localStorage.setItem("sidebarCollapsed", wasCollapsed ? "0" : "1");
    } catch (err) {
      /* per-viewer convenience only */
    }
    applyLabel();
  });
});
