# PROMPT 2 · PROOF

## Check the backtester

Build the backtester and check it on fake data, before any real result goes through it.

1. Write `src/backtest.py`. It takes bars and a signal, follows the backtest house rules, and returns equity, the list of trades and the report numbers. The first time a signal is used, a look-ahead guard picks 30 random days (seed 7), works out the signal on each one using only the data up to that day, and compares it with the signal worked out from all the data. If any differ, it stops with the error `"signal uses future data"`. A signal that passed isn't checked again unless its code changes.

2. Start `src/signals.py` with the trend switch, which the core uses: at each close, hold the engine if it closes above its line, otherwise hold the safe asset, trading at the next open. The engine, the safe asset and the line length are settings.

3. Make 1,500 days of fake bars with `rng = numpy.random.default_rng(seed)`, drawing in this order:  
   `open_moves = rng.normal(0, 0.005, 1500)`,  
   `close_moves = rng.normal(0, 0.008, 1500)`,  
   `flags = rng.random(1500) < 0.10`.  
   Each day's open is the previous close times `(1 + its open move)`, with 100 as the close before day 1, and its close is that open times `(1 + its close move)`. The high is the larger of open and close times 1.002, and the low is the smaller times 0.998. The test strategy buys at the next open after every flagged close and sells at the open after that, and every flag is its own trade, even when two overlap.

4. Run three checks, with the pass ranges fixed now:

   - **Planted edge, seed 7**: after every flagged close on day t, multiply every price from the open of day t+2 onward by 1.01, which adds 1% to that trade. Passes if the average trade is between 0.6% and 1.2%, which is the planted 1% minus 0.1% of costs, give or take noise.

   - **Pure noise, seed 8**: the same kind of bars and flags with nothing added. Passes if the average trade is between -0.4% and 0.2%.

   - **Cheating signal**, on the planted-edge bars: buy when the next day's close is higher than today's. Passes if the guard stops it with `"signal uses future data"`. Then run the real trend switch through the same guard, on the market ticker with the cash ticker as the safe asset. It must get through.

5. If a check fails, fix the backtester and run all three again. Save `results/engine_check.json` with each check, its pass range, its result and pass or fail.

### Dashboard section `02_engine`:

The planted edge, with the strategy's equity on the fake prices and the average trade against its pass range; pure noise, the same way; and the cheating signal, showing it was stopped and the real switch got through.

### FINGERPRINT P2:

```
planted edge=<x>% <pass/fail>, noise=<x>% <pass/fail>, cheating signal=<stopped/not stopped>, real signal=<pass/fail>
```
