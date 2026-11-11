// Click any Mermaid diagram to open it at its natural size in an overlay.
// Material replaces each <pre class="mermaid"> with a rendered element, so
// the sources are captured first (this script runs before DOMContentLoaded).
(function () {
  "use strict";
  var sources = Array.prototype.map.call(
    document.querySelectorAll("article pre.mermaid code"),
    function (el) { return el.textContent; }
  );
  var counter = 0;

  function close(overlay, onKey) {
    overlay.remove();
    document.removeEventListener("keydown", onKey);
    document.body.style.overflow = "";
  }

  function open(index) {
    if (typeof mermaid === "undefined" || !sources[index]) { return; }
    var overlay = document.createElement("div");
    overlay.className = "diagram-zoom";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-label", "Diagram at full size. Press Escape to close.");
    overlay.innerHTML = '<button type="button" class="diagram-zoom__close" aria-label="Close">×</button>' +
      '<div class="diagram-zoom__canvas"></div>';
    function onKey(event) {
      if (event.key === "Escape") { close(overlay, onKey); }
    }
    overlay.addEventListener("click", function (event) {
      if (event.target === overlay || event.target.classList.contains("diagram-zoom__close")) {
        close(overlay, onKey);
      }
    });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(overlay);
    document.body.style.overflow = "hidden";
    overlay.querySelector(".diagram-zoom__close").focus();
    mermaid.render("diagram-zoom-" + (counter++), sources[index]).then(function (result) {
      overlay.querySelector(".diagram-zoom__canvas").innerHTML = result.svg;
      var svg = overlay.querySelector("svg");
      var box = svg.viewBox && svg.viewBox.baseVal;
      if (box && box.width) {
        svg.style.maxWidth = "none";
        svg.style.width = Math.max(box.width, 600) + "px";
        svg.removeAttribute("height");
      }
    });
  }

  document.addEventListener("click", function (event) {
    var target = event.target.closest && event.target.closest("article .mermaid");
    if (!target) { return; }
    var all = Array.prototype.slice.call(document.querySelectorAll("article .mermaid"));
    open(all.indexOf(target));
  });
})();
