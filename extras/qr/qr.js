// Maakt de QR-code helemaal in de browser; er gaat niets naar de server.
(function () {
  "use strict";
  qrcode.stringToBytes = qrcode.stringToBytesFuncs["UTF-8"];

  var MARGIN = 4; // witte rand in modules, zoals de QR-standaard vraagt
  var text = document.getElementById("text");
  var size = document.getElementById("size");
  var canvas = document.getElementById("canvas");
  var result = document.getElementById("result");
  var error = document.getElementById("error");
  var copied = document.getElementById("copied");
  var current = null;

  function make(value) {
    // Kleinste versie die past, met foutcorrectie M (blijft leesbaar bij wat vuil).
    var qr = qrcode(0, "M");
    qr.addData(value);
    qr.make();
    return qr;
  }

  function draw() {
    var value = text.value.trim();
    error.hidden = true;
    copied.hidden = true;
    if (!value) {
      result.hidden = true;
      current = null;
      return;
    }
    try {
      current = make(value);
    } catch (e) {
      result.hidden = true;
      current = null;
      error.textContent = "Deze tekst is te lang voor een QR-code.";
      error.hidden = false;
      return;
    }
    var count = current.getModuleCount() + 2 * MARGIN;
    var cell = Math.max(1, Math.floor(Number(size.value) / count));
    var px = cell * count;
    canvas.width = px;
    canvas.height = px;
    var ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, px, px);
    ctx.fillStyle = "#000";
    for (var r = 0; r < current.getModuleCount(); r++) {
      for (var c = 0; c < current.getModuleCount(); c++) {
        if (current.isDark(r, c)) {
          ctx.fillRect((c + MARGIN) * cell, (r + MARGIN) * cell, cell, cell);
        }
      }
    }
    result.hidden = false;
  }

  function filename(ext) {
    var name = text.value.trim()
      .replace(/^[a-z]+:\/\//i, "")
      .replace(/[^a-z0-9]+/gi, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 50);
    return "qr-" + (name || "code") + "." + ext;
  }

  function download(href, name) {
    var a = document.createElement("a");
    a.href = href;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  function svg() {
    var n = current.getModuleCount();
    var total = n + 2 * MARGIN;
    var path = "";
    for (var r = 0; r < n; r++) {
      for (var c = 0; c < n; c++) {
        if (current.isDark(r, c)) path += "M" + (c + MARGIN) + " " + (r + MARGIN) + "h1v1h-1z";
      }
    }
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + total + " " + total +
      '" shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff"/>' +
      '<path d="' + path + '" fill="#000"/></svg>';
  }

  text.addEventListener("input", draw);
  size.addEventListener("change", draw);
  document.getElementById("form").addEventListener("submit", function (e) { e.preventDefault(); });

  document.getElementById("png").addEventListener("click", function () {
    if (current) download(canvas.toDataURL("image/png"), filename("png"));
  });

  document.getElementById("svg").addEventListener("click", function () {
    if (!current) return;
    var url = URL.createObjectURL(new Blob([svg()], { type: "image/svg+xml" }));
    download(url, filename("svg"));
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  });

  var copy = document.getElementById("copy");
  if (!navigator.clipboard || !window.ClipboardItem) {
    copy.hidden = true;
  }
  copy.addEventListener("click", function () {
    if (!current) return;
    canvas.toBlob(function (blob) {
      navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]).then(function () {
        copied.hidden = false;
      });
    });
  });

  // Een adres meegeven kan ook: https://qr.example.org/#https://example.org
  if (location.hash.length > 1) {
    try {
      text.value = decodeURIComponent(location.hash.slice(1));
    } catch (e) {
      text.value = location.hash.slice(1);
    }
  }
  draw();
})();
