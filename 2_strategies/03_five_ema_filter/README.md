# 5 EMA + 200 EMA Slope Filter — Single-Asset Weekly Trend on BTC

**Status:** 🟡 Research-validated 2018-2026, awaiting live deployment decision

---

## 1. Hypothesis

Bitcoin exhibits multi-month directional trends interrupted by sharp reversals. A simple short-period exponential moving average (5 EMA) can act as a binary trend filter on the weekly timeframe — long when price is above it, flat when below. To avoid whipsaw losses during sustained downtrends, an additional regime filter (the daily 200 EMA rising over the trailing 20 days) gates entries to confirmed uptrend conditions.

The thesis: **most retail traders lose money trying to short crypto bear markets. The disciplined alternative is to simply step aside.** This strategy tests whether stepping aside (and re-engaging when the longer trend resumes) outperforms passive buy-and-hold.

## 2. Strategy Specification

### Entry
- **Trend filter (gating):** Daily 200 EMA rising — `EMA200[today] > EMA200[20 days ago]`
- **Signal:** Weekly close > 5 EMA on weekly closes
- **Execution:** Enter long at next bar's open

### Exit
- **Signal:** Weekly close < 5 EMA → exit at next bar's open
- **No fixed stop, no profit target** — pure trend-filter exit

### Position Management
- **Long-only, no shorting** (shorting was tested and rejected)
- **100% all-in sizing** — full account each entry
- **Fees:** 0.10% per leg

## 3. Backtest Results (2018-01 to 2026-05)

| Variant | Trades | WR% | Final | APY | Max DD |
|---|---|---|---|---|---|
| **V0** long-only, no filter | 51 | 35.3% | $23,099 | +35.2% | -63.7% |
| **V1** long-only + filter (shipped) | 31 | 41.9% | **$28,542** | **+38.6%** | **-40.2%** |
| V2 long/short + filter | 60 | 38.3% | $12,584 | +25.7% | -70.7% |
| BTC buy-and-hold (benchmark) | — | — | $10,503 | +23.1% | -77.0% |

Starting capital: $1,839.

**Result:** The filter-gated long-only version (V1) outperforms B&H by **~3x** with about **half the drawdown**.

## 4. Why Long-Only (Not Long/Short)

The intuition that shorts during downtrends should add value turned out to be wrong. Across all timeframes, shorts barely break even:

| TF | Short Trades | Short WR | Short Avg Return | Short Total |
|---|---|---|---|---|
| 1D | 165 | 27.3% | +0.10% | +15.8% |
| 5D | 39 | 23.1% | +0.23% | +8.9% |
| 1W | 29 | 34.5% | +1.71% | +49.6% |

**Why shorts fail:** the 200 EMA slope filter is lagging — by the time it confirms a downtrend, most of the crash has already happened. Shorts catch leftover chop and brutal bear rallies. **Stepping aside (V1) is structurally better than going short (V2).**

## 5. Walk-Forward Note

This strategy was not formally walk-forward split in the same P1/P2 framework as Apex (the BTC dataset spans 8.4 years, which provides ~3 cycles for implicit validation). However:

- 2018 bear: V1 -36% vs B&H -73% (filter saved you)
- 2022 bear: V1 -56% vs B&H -64% (filter helped but bear rallies hurt)
- 2024 bull: V1 +73% vs B&H +112% (lagged, but participated)
- 2025 chop: V1 -29% vs B&H -7% (worse than B&H in choppy regime)

The 2025 underperformance is the watch-item — the strategy does not protect against whipsaws in flat-to-slightly-down regimes.

## 6. Honest Caveats

- **Single-asset, single-parameter strategy** — no formal walk-forward, no sensitivity grid. Lower confidence than Apex.
- **All-in sizing is binary and brutal** — 40% drawdown means 40% of your trading capital is gone during the worst stretch.
- **8.4 years is one Bitcoin cycle** — limited statistical confidence for forward extrapolation.
- **Funding costs not modeled** — running this on perpetuals would face funding drag during prolonged long positions.

## 7. Files

- [`backtest.py`](backtest.py) — full multi-timeframe (1D, 5D, 1W) backtest with V0 (no filter), V1 (filter-gated), V2 (long/short) variants
- [`results/equity_vs_buy_and_hold.png`](results/equity_vs_buy_and_hold.png) — 3-panel comparison of all variants vs BTC buy-and-hold across timeframes

## 8. Realistic Forward Expectation

- **Forward APY:** 20-30% (discounting the in-sample 38.6%)
- **Forward max DD:** 40-55%
- **Trade frequency:** 3-6 per year on weekly TF — very low maintenance
- **Best use case:** as a single-asset complement to multi-asset systems, or as a HODL-replacement for someone who can't sit through 70%+ drawdowns
