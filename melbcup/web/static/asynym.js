// AsynymBet (ASYNYM=1): small touches on top of pages that already work without JavaScript.
// Live refresh and the "R2 jumps in 4:12" countdown come from app.js; bets are recorded by the
// script in _bets_js.html.
(function () {
  "use strict";

  // app.js skips a refresh while a form has an edited field. Mark one in the page while the
  // Agencies panel or the Mine amounts are being changed, so a refresh does not close them.
  function hold(on) {
    var h = document.getElementById("hold");
    if (h) h.value = on ? "1" : "";
  }

  // The Agencies panel: aria-expanded on the switch label, and a money box only while ON.
  document.addEventListener("change", function (e) {
    var t = e.target;
    if (!t || !t.classList) return;
    if (t.id === "agt") {
      var label = document.querySelector('label.set[for="agt"]');
      if (label) label.setAttribute("aria-expanded", String(t.checked));
      hold(t.checked);
    } else if (t.classList.contains("sw")) {
      var row = t.closest(".agrow");
      if (row) row.classList.toggle("off", !t.checked);
    }
  });

  // Mine: Edit turns every dollar amount into an input in place; Done saves (the form submits).
  // Without JavaScript the Edit link reloads the page with ?edit=1 and does the same.
  document.addEventListener("click", function (e) {
    var edit = e.target.closest && e.target.closest("#pool-edit");
    if (!edit) return;
    e.preventDefault();
    var pool = document.getElementById("pool");
    if (!pool) return;
    pool.classList.add("editing");
    hold(true);
    var first = pool.querySelector(".mi");
    if (first) first.focus();
  });
  var pool = document.getElementById("pool");
  if (pool && pool.classList.contains("editing")) hold(true);
})();
