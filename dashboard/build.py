#!/usr/bin/env python3
"""Build dashboard/index.html by joining dashboard/sections in name order.

The result is a single self-contained HTML file that opens by
double-click (file://) with no server.
"""

from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SECTIONS_DIR = HERE / "sections"
OUT = HERE / "index.html"
ROOT = HERE.parent
STUDY_JSON = ROOT / "results" / "asset_study.json"

GROUPS_JSON = {
    "Stock indices": ["SPY", "QQQ", "IWM", "DIA"],
    "Sectors": [
        "XLK",
        "XLF",
        "XLE",
        "XLV",
        "XLI",
        "XLY",
        "XLP",
        "XLU",
        "XLB",
        "XLC",
        "XLRE",
    ],
    "Bonds": ["TLT", "IEF", "SHY"],
    "Cash": ["SGOV"],
    "Metals": ["GLD", "SLV"],
    "Commodities": ["USO", "DBC"],
    "Leveraged ETFs": ["TQQQ", "SQQQ"],
    "Crypto": ["BTC-USD"],
}

PLOTLY_CDN = "https://cdn.plot.ly/plotly-3.0.1.min.js"


def _plotly_script_tag() -> str:
    """Inline the full plotly.js as a base64 data URI so the dashboard keeps
    working with a double-click and no network. The CDN script is listed
    first so machines that are online render faster."""
    try:
        import plotly as _pl

        here = Path(_pl.__file__).resolve().parent
        js_path = here / "package_data" / "plotly.min.js"
        blob = base64.b64encode(
            js_path.read_text(encoding="utf-8").encode("utf-8")
        ).decode("ascii")
        return (
            f'<script src="{PLOTLY_CDN}"></script>\n'
            f'<script src="data:text/javascript;base64,{blob}"></script>'
        )
    except (OSError, AttributeError):
        return f'<script src="{PLOTLY_CDN}"></script>'


CSS = """
:root {
  --teal: #0f766e;
  --navy: #1e3a5f;
  --bronze: #a16207;
  --ink: #111111;
  --bg: #eef4f7;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  color: var(--ink);
  background-color: var(--bg);
  background-image:
    linear-gradient(rgba(15, 118, 110, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(15, 118, 110, 0.07) 1px, transparent 1px);
  background-size: 24px 24px;
  font-family: "Segoe UI", "Helvetica Neue", Arial, "Liberation Sans", sans-serif;
}
.page { max-width: 1200px; margin: 0 auto; padding: 28px 20px 64px; }
header.masthead {
  font-size: 1.9rem; font-weight: 650; letter-spacing: 0.02em;
  color: var(--navy); margin: 0.2em 0 1.2em;
}
section.panel {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid var(--teal);
  border-radius: 6px;
  padding: 22px 26px;
  margin: 0 0 34px;
  scroll-margin-top: 20px;
}
section.panel h2 { margin: 0 0 4px; font-size: 1.25rem; font-weight: 650; color: var(--navy); }
section.panel p.sub { margin: 0 0 18px; font-size: 0.95rem; color: var(--ink); }
.panel .main { width: 100%; }
table.settings { border-collapse: collapse; width: 100%; font-size: 0.95rem; }
table.settings th, table.settings td {
  text-align: left; padding: 7px 12px; border-bottom: 1px solid rgba(15, 118, 110, 0.25);
}
table.settings th { color: var(--teal); font-weight: 650; white-space: nowrap; }
table.asset-table { font-size: 0.85rem; }
table.asset-table td, table.asset-table th { white-space: nowrap; }
table.asset-table td.grp {
  background: rgba(30, 58, 95, 0.06); font-weight: 650; color: var(--navy);
  padding-top: 10px; padding-bottom: 6px;
}
.accent-teal { color: var(--teal); font-weight: 650; }
.accent-bronze { color: var(--bronze); font-weight: 650; }
footer.colophon { font-size: 0.8rem; color: rgba(17, 17, 17, 0.55); text-align: center; }

/* presenter tools */
#mouse-ring {
  position: fixed; width: 26px; height: 26px; border: 2px solid var(--bronze);
  border-radius: 50%; pointer-events: none; z-index: 999;
  transform: translate(-50%, -50%); opacity: 0.85;
}
#ink-canvas { position: fixed; inset: 0; width: 100vw; height: 100vh; pointer-events: none; z-index: 998; }

/* present mode: one panel at a time, bottom-right corner kept empty for the camera */
body.presenting .page { display: none; }
#stage {
  position: fixed; inset: 0; z-index: 500; background: var(--bg);
  background-image:
    linear-gradient(rgba(15, 118, 110, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(15, 118, 110, 0.07) 1px, transparent 1px);
  background-size: 24px 24px;
  overflow: hidden; display: none;
}
body.presenting #stage { display: block; }
#stage .stage-inner {
  position: absolute;
  left: 0; top: 0;
  width: 75vw; height: 70vh;   /* bottom-right 25% x 30% stays empty */
  display: flex; align-items: center; justify-content: center;
}
#stage section.panel {
  margin: 0;
  overflow: hidden;
  transform-origin: center center;
}
#stage .stage-count {
  position: absolute; left: 16px; bottom: 10px; font-size: 0.85rem; color: var(--navy);
}
"""

JS = """
// ---- presenter tools ------------------------------------------------------
(function () {
  var ring = document.getElementById("mouse-ring");
  var canvas = document.getElementById("ink-canvas");
  var ctx = canvas.getContext("2d");

  function sizeCanvas() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  }
  sizeCanvas();
  window.addEventListener("resize", sizeCanvas);

  // amber ring follows the mouse
  window.addEventListener("mousemove", function (e) {
    ring.style.left = e.clientX + "px";
    ring.style.top = e.clientY + "px";
  });

  // shift + drag draws an amber highlighter stroke that fades ~2s after release
  var drawing = false, stroke = [];
  function drawStroke() {
    if (stroke.length < 2) return;
    ctx.strokeStyle = "#d97706";
    ctx.lineWidth = 10;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.globalAlpha = 0.8;
    ctx.beginPath();
    ctx.moveTo(stroke[0].x, stroke[0].y);
    for (var i = 1; i < stroke.length; i++) ctx.lineTo(stroke[i].x, stroke[i].y);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
  window.addEventListener("mousedown", function (e) {
    if (!e.shiftKey || e.button !== 0) return;
    drawing = true;
    stroke = [{ x: e.clientX, y: e.clientY }];
  });
  window.addEventListener("mousemove", function (e) {
    if (!drawing) return;
    stroke.push({ x: e.clientX, y: e.clientY });
    drawStroke();
  });
  window.addEventListener("mouseup", function (e) {
    if (!drawing) return;
    drawing = false;
    var s = stroke;
    stroke = [];
    var alpha = 0.8, iv = setInterval(function () {
      alpha -= 0.05;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (alpha <= 0) { clearInterval(iv); ctx.clearRect(0, 0, canvas.width, canvas.height); return; }
      ctx.save();
      ctx.globalAlpha = Math.max(alpha, 0);
      ctx.strokeStyle = "#d97706";
      ctx.lineWidth = 10; ctx.lineCap = "round"; ctx.lineJoin = "round";
      ctx.beginPath();
      ctx.moveTo(s[0].x, s[0].y);
      for (var i = 1; i < s.length; i++) ctx.lineTo(s[i].x, s[i].y);
      ctx.stroke();
      ctx.restore();
    }, 25);
  });

  // P: one panel at a time, scaled to fill the screen with the camera corner clear;
  // arrow keys step through the panels, Escape goes back to the full page
  var stage = document.getElementById("stage");
  var panels = Array.prototype.slice.call(document.querySelectorAll(".page > section.panel"));
  var current = 0;

  function fit() {
    var box = stage.querySelector(".stage-inner");
    stage.querySelectorAll("section.panel").forEach(function (n) { n.remove(); });
    var sec = panels[current].cloneNode(true);
    box.appendChild(sec);
    var bw = box.clientWidth, bh = box.clientHeight;
    // measure natural size first, unscaled
    sec.style.transform = "none";
    var sw = sec.scrollWidth, sh = sec.scrollHeight;
    var k = Math.min(bw / sw, bh / sh, 1.4);
    sec.style.transform = "scale(" + k + ")";
    var count = stage.querySelector(".stage-count");
    count.textContent = "panel " + (current + 1) + " of " + panels.length + "  (P to exit)";
  }

  function present() {
    document.body.classList.add("presenting");
    fit();
  }
  function exitPresent() {
    document.body.classList.remove("presenting");
    stage.querySelectorAll("section.panel").forEach(function (n) { n.remove(); });
  }

  window.addEventListener("keydown", function (e) {
    if (e.key === "p" || e.key === "P") {
      if (document.body.classList.contains("presenting")) exitPresent();
      else present();
      return;
    }
    if (!document.body.classList.contains("presenting")) return;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      current = (current + 1) % panels.length;
      fit();
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      current = (current - 1 + panels.length) % panels.length;
      fit();
    } else if (e.key === "Escape") {
      exitPresent();
    }
  });
})();
"""


def build(output: Path | None = None) -> Path:
    out_path = output if output is not None else OUT
    sections = sorted(SECTIONS_DIR.glob("*.html"), key=lambda p: p.name)
    if not sections:
        raise SystemExit(f"no sections found in {SECTIONS_DIR}")

    study, corr = {}, {}
    if STUDY_JSON.exists():
        study = json.loads(STUDY_JSON.read_text(encoding="utf-8"))
        corr = study.get("correlations", {})

    needs_plotly = False
    parts = [
        '  <div class="page"><header class="masthead">AI Trading System</header>\n'
    ]
    for i, path in enumerate(sections):
        body = path.read_text(encoding="utf-8").strip()
        body = body.replace("{{DATE}}", date.today().isoformat())
        if "{{ASSET_STUDY}}" in body:
            body = body.replace("{{ASSET_STUDY}}", json.dumps(study))
        if "{{ASSET_GROUPS}}" in body:
            body = body.replace("{{ASSET_GROUPS}}", json.dumps(GROUPS_JSON))
        if "{{CORRELATIONS}}" in body:
            body = body.replace("{{CORRELATIONS}}", json.dumps(corr))
        if "Plotly.newPlot" in body:
            needs_plotly = True
        parts.append(
            f'  <section class="panel" id="panel-{i:02d}">\n    {body}\n  </section>\n'
        )
    parts.append(
        '  <footer class="colophon">built by dashboard/build.py on '
        + date.today().isoformat()
        + " &middot; double-click to open, no server needed</footer>\n"
    )
    parts.append("  </div>\n")

    plotly_tag = _plotly_script_tag() + "\n" if needs_plotly else ""

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Trading System &mdash; dashboard</title>
{plotly_tag}<style>
{CSS}
</style>
</head>
<body>
{"".join(parts)}
<div id="stage" aria-hidden="true"><div class="stage-inner"></div><div class="stage-count"></div></div>
<div id="mouse-ring" aria-hidden="true"></div>
<canvas id="ink-canvas" aria-hidden="true"></canvas>
<script>
{JS}
</script>
</body>
</html>
"""
    out_path.write_text(doc, encoding="utf-8")
    print(
        f"built {out_path} from {len(sections)} section(s): "
        + ", ".join(p.name for p in sections)
    )
    return out_path


if __name__ == "__main__":
    build()
