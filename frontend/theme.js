/* Applies the saved theme before the page paints.
 *
 * Loaded in <head> on purpose: run it after the body renders and the wrong theme flashes
 * first. Light is the default per DESIGN.md ("Light theme — primary"), so an install that
 * has never touched settings shows the warm cream palette the doc treats as the real one,
 * and dark is the opt-in. */
(function () {
  var saved = null;
  try {
    saved = localStorage.getItem("theme");
  } catch (err) {
    /* private browsing or storage disabled — light is the default and that is fine */
  }
  if (saved === "dark") document.documentElement.setAttribute("data-theme", "dark");
})();
