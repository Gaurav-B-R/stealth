/* Shared site-footer behaviour. Loaded with `defer` on every public page so the
   one footer markup block stays identical everywhere and needs no per-page glue.
   Keeps the copyright year current — the SPA fills #footerVersion itself. */
(function () {
    var year = document.getElementById("yr");
    if (year) year.textContent = new Date().getFullYear();
})();
