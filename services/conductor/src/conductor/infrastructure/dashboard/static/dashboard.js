// Equity curve. Loaded from /static (CSP: script-src 'self'); Chart.js is vendored.
(function () {
  "use strict";
  var canvas = document.getElementById("equity");
  if (!canvas || typeof Chart === "undefined") { return; }
  fetch(canvas.dataset.src, { headers: { Accept: "application/json" } })
    .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
    .then(function (body) {
      if (!body.points.length) { document.getElementById("equity-empty").hidden = false; return; }
      var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      var line = dark ? "#6cb2ff" : "#1a5fb4";
      var grid = dark ? "#2d3340" : "#e1e5ec";
      var text = dark ? "#aab2c0" : "#4a5260";
      new Chart(canvas, {
        type: "line",
        data: {
          datasets: [{
            label: "Equity (USD)",
            data: body.points.map(function (p) { return { x: new Date(p.t), y: Number(p.v) }; }),
            borderColor: line, backgroundColor: line, borderWidth: 2, pointRadius: 0, tension: 0.15
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          parsing: false, interaction: { mode: "nearest", intersect: false },
          scales: {
            x: { type: "linear", ticks: { color: text, maxTicksLimit: 6, callback: function (v) { return new Date(v).toISOString().slice(5, 16).replace("T", " "); } }, grid: { color: grid } },
            y: { ticks: { color: text, callback: function (v) { return "$" + v; } }, grid: { color: grid } }
          },
          plugins: { legend: { display: false } }
        }
      });
    })
    .catch(function () { document.getElementById("equity-empty").textContent = "Could not load the equity curve."; document.getElementById("equity-empty").hidden = false; });
})();
