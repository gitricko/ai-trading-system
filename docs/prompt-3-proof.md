# PROMPT 3 · PROOF

## Find the core:

Find the core: one simple rule that holds most of the money and only trades a few times a year. It uses the asset study from Prompt 1 and the trend switch and backtester from Prompt 2. Steps 1 to 4 use the training window only.

1. **Pick the engine**: of the engine candidates in my settings, the one with the biggest trend gap from Prompt 1.

2. **Pick the safe asset**: for each safe candidate, work out its annualized return on the engine's downtrend days and its daily correlation with the engine. Only ones with a correlation below 0.5 can be picked. The safe asset is the one with the highest return on those days, or the cash ticker if none beats it.

3. **The switch**: hold the engine while it closes above its 200-day line, otherwise hold the safe asset, trading at the next open.

4. **Neighbors**: rerun it with the 100, 150 and 250-day lines, the 200-day exponential moving average, and the 50-day average crossing the 200-day as the switch. It passes if every version makes money after costs.

5. **Locked test**: run it once. It passes if it makes money after costs.

6. **Cost check**: rerun it on both windows at double the cost in my settings.

7. If it passes steps 4 and 5, save it to `config/system.yaml` as  
   `core: engine <ticker>, safe <ticker>, line_days 200`,  
   making the file if needed and leaving the rest alone. If it fails, tell me which step it failed and save nothing.

### Outputs

Save `results/core.json` with every number, the switches per year (the first buy isn't a switch), the share of time in each ticker, and every switch with its date.

### Dashboard section `03_core`:

- Each engine candidate's trend gap  
- Each safe candidate's return on the engine's downtrend days with its correlation  
- The neighbors as a bar chart  
- The core on both windows as one equity curve with the drawdown underneath, the locked test shaded and labeled "locked test", and a strip under it showing what it held each day  
- The cost check

### FINGERPRINT P3:

```
engine=<ticker>, safe=<ticker>, train return/yr=<x>%, train max DD=<x>%, test return/yr=<x>%, test max DD=<x>%, train switches=<n>, neighbors=<pass/fail>, locked test=<pass/fail>
```
