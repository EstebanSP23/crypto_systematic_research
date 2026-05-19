# Apex — Multi-Asset 6-Month-High Breakout (No Pyramid)

**Status:** 🟡 Validated, deployable, awaiting capital allocation

---

## 1. Hypothesis

When a crypto asset closes above its highest price of the past 180 days (1080 bars on 4H), it is establishing a new multi-month high — a strong signal of trend continuation. Combined with confirmation from trend filters (50 SMA > 200 SMA) and volume expansion, this should identify durable directional moves across a basket of major crypto assets.

The "no pyramid" variant is deliberate. An earlier version with pyramiding failed walk-forward catastrophically (see `3_dead_strategies/apex_with_pyramid/`) — it was curve-fit to the 2023 bull regime.

## 2. Strategy Specification

### Universe
- BTC, ETH, SOL, LINK, ADA, ARB, SUI, SEI

### Entry (all required at 4H bar close)
- **Signal:** Close > highest high of previous 1080 bars (~180 days)
- **Trend filter:** Close > 50 SMA AND 50 SMA > 200 SMA
- **Volume confirmation:** Current volume > 1.5x 20-bar average volume

### Position Management
- **Entry execution:** Next bar's open after signal
- **Initial stop:** Entry - 2x ATR(14)
- **Scale-out:** 50% off at 2R, move remaining stop to breakeven
- **Trail:** Remaining 50% trailed with 20-bar low
- **Final exit:** Trailing stop hit

### Risk & Sizing
- **Risk per trade:** 2% of current account
- **Position size:** (account x 2%) / (entry - stop)
- **Max concurrent positions:** 3 across the 8-asset universe
- **Fees modeled:** 0.10% per leg

### Critical Design Decision: No Pyramiding
The original Apex design included a pyramid structure. It failed walk-forward badly — degraded from +122% APY in training to -0.2% APY in the fresh exam, a classic curve-fit signature. The no-pyramid version that ships here is the survivor.

## 3. Walk-Forward Validation

| Period | Trades | Win Rate | Expectancy | Max DD | APY |
|---|---|---|---|---|---|
| **P1 training (2022-23)** | 19 | 57.9% | +1.26R | -6.5% | **+24.2%** |
| **P2 fresh exam (2024-26)** | 47 | 38.3% | +0.20R | -14.1% | **+6.1%** |

**Verdict:** edge survives, but degrades significantly. The forward expectation is closer to P2 numbers than P1. **Honest forward expectation: 5-7% APY, 15-20% max DD.**

## 4. Sensitivity Grid Analysis

A 3-axis grid (lookback x ATR multiplier x volume multiplier) was tested across 27 configurations:

| Metric | Result |
|---|---|
| Configs with positive P1 expectancy | 27/27 (100%) |
| Configs with positive P2 expectancy | 27/27 (100%) |
| Configs with positive P2 APY | 26/27 (96%) |
| P2 APY range | -0.7% to +9.4% (median +6.0%) |
| P2 expectancy range | +0.03R to +0.40R (median +0.21R) |

**Robustness verdict:** strong. The edge is broad-based, not concentrated in one magic cell. This is the opposite signature of a curve-fit strategy.

## 5. Per-Asset Contribution (66 trades total across P1+P2)

| Rank | Asset | Trades | WR% | Total R | Verdict |
|---|---|---|---|---|---|
| 1 | LINK | 6 | 83.3% | +10.7R | ⭐ Star — positive every year |
| 2 | ETH | 8 | 62.5% | +7.8R | ⭐ Solid |
| 3 | SOL | 9 | 44.4% | +7.2R | ⭐ Big winners, low WR |
| 4 | ADA | 7 | 57.1% | +6.7R | ⭐ Decent |
| 5 | BTC | 17 | 35.3% | +5.8R | ⭐ Most active, weakest avg |
| 6 | SUI | 12 | 25.0% | -0.9R | 🚨 Net loser |
| 7 | SEI | 1 | 0% | -1.0R | 🚨 Inactive |
| 8 | ARB | 6 | 33.3% | -3.1R | 🚨 Structurally bad |

**Concentration risk:** Top 3 trades = 51% of total profit. Top 5 = 74%. The strategy depends on capturing rare outliers, typical of trend-following.

## 6. Files

- `backtest.py` — research backtest (to be added)
- `sensitivity_grid.py` — 27-cell parameter grid (to be added)
- `results/` — equity curves, heatmaps, per-asset diagnostics (to be added)

## 7. Honest Caveats

- **2025 P&L was -$93** — the strategy showed clear edge decay in the most recent year. This is a watch-item if deployed.
- **The 50/200 SMA filter is largely redundant** — testing showed the 180-day breakout signal is itself such a strong trend filter that the SMA filter contributes very little. Kept for safety.
- **The seasonal "Q4 trend" pattern is curve-fit folklore** — restricting trades to Oct-Feb improves backtest results but the improvement is hindsight-driven and was rejected as over-fit.

## 8. Realistic Forward Expectation

- **Forward APY:** 5-10% (matches P2 out-of-sample evidence)
- **Forward max DD:** 15-20%
- **Trade frequency:** ~20 per year across the 8-asset universe
- **Capacity:** scales linearly with capital; no microstructure constraints at retail size
