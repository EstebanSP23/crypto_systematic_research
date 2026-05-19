# Apex *with* Pyramid — Killed

**Verdict:** 🚨 Catastrophic curve-fit. Failed walk-forward by ~122 APY-points.

---

## 1. Hypothesis

The same 6-month-high breakout idea as the surviving Apex strategy, but with a 4-unit pyramid structure (adds +1N intervals as the trade extends, where N = ATR at entry). The thesis: pyramiding should amplify gains during sustained trends without proportionally amplifying losses, since a hard 5% catastrophe stop caps any single sequence's downside.

Tested on a 6-asset curated universe (BTC, ETH, SOL, LINK, ADA, SUI), 90-day lookback (540 4H bars).

## 2. Strategy Specification

- **Universe:** BTC, ETH, SOL, LINK, ADA, SUI
- **Timeframe:** 4H
- **Entry:** close > previous 540-bar high (90 days), close > 50 SMA > 200 SMA
- **Pyramid:** up to 4 units, adds at +1N intervals above original entry
- **Risk:** 2% per unit, 5% hard catastrophe stop, 2× ATR trailing exit
- **Max concurrent positions:** 3, max 20× leverage cap

## 3. Backtest Results (Walk-Forward)

| Metric | P1 Training (2022-2023) | P2 Fresh Exam (2024-2026) |
|---|---|---|
| Trades | 30 | 74 |
| Win rate | 20.0% | 14.9% |
| Expectancy | **+5.201R** | **+0.284R** |
| Avg winner | +32.07R | +10.30R |
| Biggest winner | +92.31R | +28.37R |
| Max drawdown | -41.1% | -53.9% |
| Final balance | **$9,015.83** | **$1,832.00** |
| Total return | **+390.2%** | **-0.4%** |
| **APY** | **+121.6%** | **-0.2%** |

The P1 training period showed a spectacular +121.6% APY. The same code applied to the unseen P2 period produced **-0.2% APY** — essentially flat after fees, with a worse max drawdown.

## 4. Why It Was Killed

**The P1-to-P2 collapse is one of the cleanest curve-fit signatures possible to observe:**

- APY swing: +121.6% → -0.2% (a 122-percentage-point swing)
- Expectancy decay: +5.20R → +0.28R (94% reduction)
- Biggest winner: +92R → +28R (the outliers shrunk by 70%)
- Win rate even degraded: 20% → 14.9%

The strategy worked extraordinarily in 2023 because that year had multiple sustained directional moves where a pyramid could ride for weeks. In 2024-2026, the choppier/altcoin-rotation conditions did not produce trades long enough for the pyramid to accumulate units profitably. The hard 5% stop fired repeatedly on partially-pyramided sequences.

## 5. The Lesson

**Pyramiding is the single most curve-fit-prone enhancement you can add to a trend-following backtest.** It magnifies favorable regime tailwinds in-sample, then magnifies losses out-of-sample when the regime is even slightly different.

The replacement strategy — Apex *without* pyramid ([../../2_strategies/02_apex_no_pyramid/](../../2_strategies/02_apex_no_pyramid/)) — passed walk-forward with much smaller P1-vs-P2 degradation (+24% APY → +6% APY, a 75% reduction rather than 100%). Same signal logic, no pyramid. The non-pyramid version is the one that gets to live.

## 6. Files

- Source script: `walkforward_apex.py` (in research directory, not published)
- Chart: `walkforward_apex.png` (P1 vs P2 equity curves)
