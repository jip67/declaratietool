// Tekenvlak voor de paraaf van de voorzitter: tekenen met vinger, pen of muis.
// Bij versturen gaat de tekening als PNG (data-url) mee in het verborgen veld "signature".
(function () {
  const INK = "#102a8c";

  function setup(pad) {
    const canvas = pad.querySelector("canvas");
    const input = pad.querySelector('input[name="signature"]');
    const missing = pad.querySelector("[data-signature-missing]");
    const form = pad.closest("form");
    const ctx = canvas.getContext("2d");
    let strokes = []; // lijnen als lijsten punten, in fracties van de breedte/hoogte
    let current = null;
    let saved = null; // bewaarde paraaf als afbeelding

    function lineWidth() {
      return Math.max(3, canvas.width / 110);
    }

    function redraw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (saved) {
        const scale = Math.min((canvas.width * 0.9) / saved.width, (canvas.height * 0.9) / saved.height);
        const w = saved.width * scale, h = saved.height * scale;
        ctx.drawImage(saved, (canvas.width - w) / 2, (canvas.height - h) / 2, w, h);
      }
      ctx.strokeStyle = INK;
      ctx.fillStyle = INK;
      ctx.lineWidth = lineWidth();
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      for (const s of strokes) {
        const pts = s.map(([x, y]) => [x * canvas.width, y * canvas.height]);
        if (pts.length === 1) {
          ctx.beginPath();
          ctx.arc(pts[0][0], pts[0][1], ctx.lineWidth / 2, 0, Math.PI * 2);
          ctx.fill();
          continue;
        }
        ctx.beginPath();
        ctx.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < pts.length - 1; i++) {
          const mx = (pts[i][0] + pts[i + 1][0]) / 2, my = (pts[i][1] + pts[i + 1][1]) / 2;
          ctx.quadraticCurveTo(pts[i][0], pts[i][1], mx, my);
        }
        const last = pts[pts.length - 1];
        ctx.lineTo(last[0], last[1]);
        ctx.stroke();
      }
    }

    function resize() {
      const ratio = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      const w = Math.round(rect.width * ratio), h = Math.round(rect.height * ratio);
      if (w && h && (w !== canvas.width || h !== canvas.height)) {
        canvas.width = w;
        canvas.height = h;
        redraw();
      }
    }

    function isEmpty() {
      return !saved && strokes.length === 0;
    }

    function point(e) {
      const rect = canvas.getBoundingClientRect();
      return [(e.clientX - rect.left) / rect.width, (e.clientY - rect.top) / rect.height];
    }

    canvas.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      canvas.setPointerCapture(e.pointerId);
      current = [point(e)];
      strokes.push(current);
      missing.hidden = true;
      redraw();
    });
    canvas.addEventListener("pointermove", (e) => {
      if (!current) return;
      e.preventDefault();
      const events = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
      for (const ev of events) current.push(point(ev));
      redraw();
    });
    const end = () => { current = null; };
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointercancel", end);

    pad.querySelector("[data-signature-clear]").addEventListener("click", () => {
      strokes = [];
      saved = null;
      redraw();
    });

    form.addEventListener("submit", (e) => {
      if (isEmpty()) {
        e.preventDefault();
        missing.hidden = false;
        canvas.scrollIntoView({ behavior: "smooth", block: "center" });
        return;
      }
      input.value = canvas.toDataURL("image/png");
    });

    if (canvas.dataset.saved) {
      const img = new Image();
      img.onload = () => { saved = img; redraw(); };
      img.src = canvas.dataset.saved;
    }
    window.addEventListener("resize", resize);
    resize();
  }

  document.querySelectorAll("[data-signature-pad]").forEach(setup);
})();
