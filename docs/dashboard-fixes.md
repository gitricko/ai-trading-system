# Dashboard fixes — quick reference

Short answer: **there is no server and no fix button. You rebuild the single
`dashboard/index.html` and hard-refresh the browser.** This page explains why,
and gives the recipe for common visual issues.

## 1. "I changed something but it doesn't look different"

Almost always **browser cache**, not a real bug.

- The dashboard is one self-contained `dashboard/index.html` opened by
  **double-click** (`file://`). Browsers serve `file://` pages from cache and
  **ignore** `<meta http-equiv="Cache-Control">` on them, so the stale copy
  sticks until the user forces a refresh.
- **Fix:** in the browser, hard-refresh with **Ctrl/Cmd+Shift+R** (or open the
  page in a new incognito/private window).
- **Proof it's stale, not the build:** the footer of every dashboard build
  shows a build timestamp, e.g. `built 2026-11-09 21:37:13 UTC`. Compare it to
  the moment of the last `dashboard/build.py` run. If the footer is older, the
  browser is showing a cached page.

## 2. "How do I actually fix it?" — the build recipe

```bash
cd /codespace/ai-trading-system
.venv/bin/python dashboard/build.py      # regenerates dashboard/index.html
# then in the browser: Ctrl/Cmd+Shift+R
```

`build.py` joins `dashboard/sections/*.html` (in filename order), injects data
from `results/`, inlines `plotly.js` so the page works offline, stamps the
footer, and writes `dashboard/index.html`. Every change to the dashboard is:
**edit a section → build → hard refresh**. CI does the same build for every PR,
so a green CI means the built page compiles.

## 3. "The chart has whitespace below / around it"

Plotly charts are drawn inside a fixed-size SVG box, and any legend or padding
you ask Plotly for **reserves space** inside that box. The reliable way to
remove extra whitespace is to **measure, not guess**:

1. Give the chart a fixed `height` in its Plotly layout (e.g. `height: 415`).
2. Keep bottom `margin.b` small (28–40 px) and put the **legend in plain HTML
   below the chart** (see `dashboard/sections/02_market.html`, class
   `spy-legend`) rather than in Plotly's `legend` — Plotly's legend eats extra
   vertical space and is harder to size.
3. Verify with a headless render, not by eyeballing:

   ```bash
   chromium --headless --no-sandbox --window-size=1400,3200 \
     --virtual-time-budget=15000 --dump-dom \
     "file://$PWD/dashboard/index.html" > /tmp/dom.html
   ```

   In a copy of the page append a script that logs
   `getElementById('your-chart').querySelector('.main-svg').getBoundingClientRect()`
   and the legend's rect, then print the pixel gap between the last x-axis
   label and the legend top. Target a gap of ~20–30 px.

## 4. House style for new charts in the dashboard

- Colors from `:root` in `dashboard/build.py`: teal `#0f766e`, navy `#1e3a5f`,
  bronze `#a16207`, text `#111` on a pale-blue/white background.
- Fonts: the page font is `Segoe UI / Helvetica / Arial / sans-serif` — set the
  same on Plotly's `font.family`.
- Every new section is a file in `dashboard/sections/` named `NN_name.html`
  so it sorts in order and gets its own `id="panel-NN"`.
- All JS must work under `file://` (no fetch, no modules, no network) — data
  is injected by `build.py` from `results/*.json`.

## 5. If you add a new data file for a section

1. Write it into `results/` (e.g. in `asset_study.py`) — it must survive a
   re-run of the study script, and must use the **training window only** for
   any *derived* stat (prices may be plotted, labels must not peek past
   2024-12-31).
2. In `dashboard/build.py`, add a `{{PLACEHOLDER}}` substitution for it (see
   how `{{SPY_LINE}}` is wired in).
3. Use the placeholder in the section file. Build, hard-refresh, measure.
