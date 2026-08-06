/* Applies the saved theme before the page paints.
 *
 * Loaded in <head> on purpose: run it after the body renders and the wrong theme flashes
 * first. Dark is the default, so an install that has never touched settings looks exactly
 * as it did before this existed. */
(function () {
  var saved = null;
  try {
    saved = localStorage.getItem("theme");
  } catch (err) {
    /* private browsing or storage disabled — dark is the default and that is fine */
  }
  if (saved === "light") document.documentElement.setAttribute("data-theme", "light");
})();
