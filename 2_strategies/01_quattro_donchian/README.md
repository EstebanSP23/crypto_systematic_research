# Quattro — Donchian Breakout with 4-Unit Pyramid

**Status:** 🟢 Live on BloFin perpetual futures since May 2026

---

## 1. Hypothesis

Crypto markets exhibit persistent trends after volatility-expanded breakouts from prior highs. A pyramiding entry structure that adds size as the trend extends can capture asymmetric upside, provided risk is tightly managed at each addition and a hard catastrophe stop prevents disaster on failed breakouts.

This is the textbook **Donchian-Turtle-style trend follower** applied to BTC 4H, with a regime filter to avoid bear markets.

## 2. Strategy Specification

### Entry
- **Signal:** Close > previous 20-bar high (Donchian breakout)
- **Trend filter:** Daily 200 EMA must be rising (daily_EMA200[d] > daily_EMA200[d-20])
- **Execution:** Enter long at the next bar's open

### Pyramid Structure
- **Maximum units:** 4
- **Add levels:** Unit 2 at +0.5N, Unit 3 at +1.0N, Unit 4 at +1.5N (where N = ATR(14) at original entry, fixed for the entire sequence)
- **Each unit risks:** 2% of account at original entry, sized off 2N stop distance

### Exit Logic (three independent mechanisms)
- **Donchian channel exit:** close < previous 10-bar low → close ALL units at next bar's open
- **Per-unit trailing stop:** stop = newest unit's entry − 2N (wick-based). Tightens only when a new unit is added, not continuously as price moves.
- **Hard catastrophe stop:** combined unrealized loss reaches 5% of account (wick-based)
- **No fixed profit target** — the Donchian channel and the unit-based trail do the work

In live results, the three exit reasons split roughly: 40% hard stops, 36% Donchian exits, 23% trailing stops.

### Other Rules
- Single asset (BTC) — no multi-asset complexity
- 4H timeframe — strikes a balance between signal frequency and fee drag
- No shorting — long-only

## 3. Backtest Results

### Headline

| Metric | Value |
|---|---|
| Period | Jan 2022 – May 2026 (~4.1 years of live signals; first entry Mar 28, 2022) |
| Starting capital | $1,839 |
| Final account | $22,196 |
| Total return | **+1,107%** |
| APY | **+83%** |
| Max drawdown | **-37.5%** |
| Total trades | 94 (pyramid sequences, each may contain up to 4 unit entries) |
| Avg trade duration | 3.2 days |

### Trade Distribution

| Metric | Value |
|---|---|
| Wins | 25 (**26.6%**) |
| Losses | 69 (73.4%) |
| Average winner | **+13.4R** |
| Average loser | -2.0R |
| Win/loss asymmetry | **6.7x** |
| Best trade | +76.7R |
| Worst trade | -2.5R (capped by 5% catastrophe stop) |

### R-Distribution

| R Bucket | Count | % of trades |
|---|---|---|
| Loss > -1R (mostly -2.5R catastrophe stops) | 59 | 63% |
| Loss -1R to 0R | 10 | 11% |
| Win 0 to 5R | 10 | 11% |
| Win 5R to 10R | 4 | 4% |
| **Win > 10R (the trend-capture moonshots)** | **11** | **12%** |

This is a textbook trend-follower profile: **low win rate, occasional massive winners, many small-to-medium losses, capped catastrophic risk.** The 11 trades that returned >10R generate the bulk of the lifetime P&L. The strategy works because the asymmetry math overwhelms the win-rate math.

### Trades by Year

| Year | Trades |
|---|---|
| 2022 (partial, from March) | 1 |
| 2023 | 30 |
| 2024 | 32 |
| 2025 | 29 |
| 2026 YTD (through May) | 2 |

### Exit Reason Breakdown

| Exit Reason | Count | % |
|---|---|---|
| Hard 5% catastrophe stop | 38 | 40% |
| Donchian channel exit (close < 20-bar low) | 34 | 36% |
| 2x ATR trailing stop | 22 | 23% |

Note: the high count of catastrophe stops (40%) is expected for a pyramiding breakout strategy. Most breakouts fail. The catastrophe stop is the *floor*, not the average — the average loser is only -2.0R because many pyramid sequences exit before reaching the 5% combined-position floor.

## 4. Walk-Forward Validation

The strategy was tested on a split walk-forward:
- **Period 1 training (2022-2023):** edge confirmed across the 2022 bear and 2023 recovery
- **Period 2 fresh exam (2024-2026):** edge held — 32 trades in 2024, 29 in 2025, continuing positive expectancy

Both halves produced positive expectancy and were structurally similar in trade frequency (~30 per year). The strategy's edge is not concentrated in a single bull regime.

## 5. Operational Specification

The live deployment includes operational safety features built around the strategy logic:

- **Startup safety check** — bot refuses to start with stale state or pending positions
- **Auto-recovery** — systemd restarts on crash with state reload from the trade log
- **Daily heartbeat** — confirms the bot is alive even when no trades fire
- **Reconciliation** — exchange state checked against local state every hour
- **Margin pre-check** — refuses entries that would exceed available margin
- **Telegram alerts** — all entries, exits, and reconciliation events broadcast in real time

## 6. Capital Allocation

- **Account size:** $1,841 USDT total
- **Trading allocation:** $800 (4-unit pyramid worst-case margin)
- **Buffer:** ~$200 (margin safety)
- **Earn buffer:** $1,041 in BloFin Earn (tiered yield)

The trading allocation is intentionally less than the account total because the pyramid can scale aggressively under favorable conditions, and the strategy has been observed to consume 60-70% of available margin in deep extensions.

## 7. Files

- [`backtest.py`](backtest.py) — full research backtest script (CCXT-based, no API keys; reproducible from Binance public OHLCV)
- [`results/quattro_equity_curve.png`](results/quattro_equity_curve.png) — equity curve over the 4.1-year backtest

> **Note:** The live production code (with API keys, exchange credentials, and systemd service files) is intentionally **not** included in this public repository. Only research code is published.

## 8. Realistic Forward Expectation

- **Forward APY:** 30-60% (notably lower than the +83% backtest headline; reflects honest expectation under live conditions including slippage, funding, and execution delay)
- **Forward max DD:** 35-50% (consistent with or slightly worse than backtest)
- **Trade frequency:** ~25-35 sequences per year (~one every 10-14 days on average)
- **Psychological note:** the 26.6% win rate means **you will lose ~3 of every 4 trades**. Sitting through this requires faith in the asymmetry math, not in any single trade outcome.

## 9. Break-even variants (tested, rejected)

Script: [`backtest_breakeven_variants.py`](backtest_breakeven_variants.py) → [`results/breakeven_variants.csv`](results/breakeven_variants.csv). Same data and period (Jan 2022 – May 2026), same rules; only the stop changes:

- **A** Baseline — current system
- **B** Break-even when Unit 4 fills: `common_stop = max(common_stop, weighted avg entry)`
- **C** Break-even once close > weighted avg entry + 1N (N = ATR at original entry)
- **D** Same as C, plus the Donchian exit uses the 5-bar low (instead of 10) once Unit 4 is in

"Given back" = trades whose bar high exceeded weighted avg entry + 1N and still closed negative. 0R exits are counted separately (not wins, not in avg loss). Max DD on closed-trade equity; no fees.

**Full period (Jan 2022 – May 2026)**

| Variant | Return | APY | Max DD | Trades | Win rate | Avg win R | Avg loss R | 0R exits | Given back |
|---|---|---|---|---|---|---|---|---|---|
| A Baseline | **+1,107%** | **78.5%** | −37.5% | 94 | 26.6% | +13.42 | −2.01 | 0 | 25 |
| B BE @ Unit 4 | +875% | 69.9% | −37.7% | 112 | 14.3% | +17.22 | −1.78 | 41 | 5 |
| C BE @ +1N | +564% | 55.3% | −47.7% | 104 | 16.3% | +17.17 | −1.94 | 20 | 16 |
| D BE @ +1N + Donchian 5 | +476% | 50.3% | −44.7% | 107 | 18.7% | +14.13 | −1.90 | 18 | 16 |

**Walk-forward** (single run split by entry date; P2 measured from the equity P1 ended with)

| Period · Variant | Return | APY | Max DD | Trades | Win rate | Avg win R | Avg loss R | 0R exits | Given back |
|---|---|---|---|---|---|---|---|---|---|
| P1 2022-23 · A | +288% | 105.3% | −30.8% | 31 | 22.6% | +22.99 | −2.11 | 0 | 8 |
| P1 2022-23 · B | **+352%** | **122.6%** | **−22.2%** | 33 | 18.2% | +24.93 | −1.89 | 9 | 2 |
| P1 2022-23 · C | +302% | 109.3% | −27.2% | 31 | 19.4% | +26.25 | −2.07 | 3 | 6 |
| P1 2022-23 · D | +295% | 107.2% | −28.6% | 32 | 18.8% | +26.78 | −2.02 | 3 | 6 |
| P2 2024-26 · A | **+211%** | **60.0%** | −37.5% | 63 | 28.6% | +9.70 | −1.95 | 0 | 17 |
| P2 2024-26 · B | +116% | 37.5% | −37.7% | 79 | 12.7% | +12.60 | −1.73 | 32 | 3 |
| P2 2024-26 · C | +65% | 23.1% | −47.7% | 73 | 15.1% | +12.21 | −1.87 | 17 | 10 |
| P2 2024-26 · D | +46% | 17.0% | −44.7% | 75 | 18.7% | +8.70 | −1.84 | 15 | 10 |

**Why rejected**

- Break-even does cut given-back trades (25 → 5 in B, 16 in C/D), but win rate drops from 26.6% to 14–19%: many trends revisit the average entry before continuing, get stopped at 0R and are re-entered at a worse price.
- Every variant beats the baseline in P1 but loses in P2 (B +116%, C +65%, D +46% vs +211%): the improvement does not hold out of sample.
- C and D also deepen max drawdown to −45%/−48%, and B trades 19% more often, which fees would punish further.

> Sensitivity: `--realistic-fills` (the higher stop is hit first; fill at min(open, stop)) → [`results/breakeven_variants_realistic_fills.csv`](results/breakeven_variants_realistic_fills.csv). The baseline improves too (+1,274%); B edges it on the full period (+1,403%) but still loses in P2 (+188% vs +228%), so the verdict stands.

## 10. Baseline v2 (costos reales)

[`backtest_quattro_v2_costs.py`](backtest_quattro_v2_costs.py) runs the same system as `backtest.py` (same data and period) and adds a 0.06% taker fee on every fill (entry, each pyramid unit, exit) plus perpetual funding charged at each 00/08/16 UTC settlement on the open notional (positive funding costs the long). Fees and funding are debited from the balance when they occur, and that balance sizes the next units and trades; `--no-costs` reproduces the original trade by trade (94 trades, $22,196). Funding history comes from the Binance BTC/USDT:USDT perpetual ([`1_data/btc_funding_binance.csv`](../../1_data/btc_funding_binance.csv)) as a proxy for BloFin, which does not publish a long history. With costs, the 94 trades and the 26.6% win rate are unchanged, but total return falls from +1,107% to **+610%** (APY 78.5% → **57.8%**), max drawdown deepens from −37.5% to **−41.7%** and Calmar drops from 2.09 to **1.39**. Costs split almost evenly: $2,428 in fees (15.4R) vs $2,154 in funding (14.4R). The hit is larger in P2 2024-26 (APY 60.0% → 38.2%, Calmar 1.60 → 0.92) than in P1 2022-23 (APY 105.3% → 87.0%): costs are ~0.32R per trade in both halves, but P2 has twice the trades and a thinner edge per trade (avg win 9.7R vs 23.0R). The ten largest winners paid 0.3–2.9R each in funding (at most 9.7% of their gross P&L, in Feb–Mar 2024). Full table: [`results/quattro_v2_costs.csv`](results/quattro_v2_costs.csv); top-10 funding: [`results/quattro_v2_top10_funding.csv`](results/quattro_v2_top10_funding.csv). Slippage is still not modeled.

## 11. Round 2 (v2 engine)

All Round 2 experiments run on [`quattro_v2_engine.py`](quattro_v2_engine.py), a parametrized copy of the v2 logic (taker 0.06% + Binance funding debited from the balance) that verifies on every run that it reproduces v2 exactly, and are compared against **v2, not the original**. Acceptance criteria were fixed in advance: **(a)** Calmar better than v2 in P1 2022-23 **and** in P2 2024-26, **(b)** at least 70% of v2's trades, **(c)** a one-sentence economic rationale. Failing any one means rejected.

**Experiment 1 — no entries on Sunday-close signal bars** ([`backtest_v2_no_sunday.py`](backtest_v2_no_sunday.py), [`results/round2_no_sunday.csv`](results/round2_no_sunday.csv)). Variant 1a skips a new trade when the signal bar closes on Sunday UTC; variant 1b also defers pyramid units on Sunday-close bars (filled on the next allowed bar at max(trigger, open)). Only 8 of v2's 94 entries have a Sunday signal, and in 6 of them the breakout still holds on Monday, so the filter mostly delays the entry by a bar or two (92 trades, 98% of v2). Full-period return edges up (+618% / +614% vs +610%), but max drawdown deepens from −41.7% to −43.3%. Calmar improves in P1 (2.69 vs 2.60) and worsens in P2 (0.86 / 0.85 vs 0.92), so **1a and 1b are both REJECTED on criterion (a)**; (b) and (c) pass (Sunday-close breakouts form in the week's thinnest liquidity, with CME, ETFs and most desks closed). Caveat: the Sunday idea came from the 2019-2026 breakout study, so P1/P2 were not out-of-sample for this hypothesis.

**Experiment 2 — pyramid cap on extreme funding** ([`backtest_v2_funding_cap.py`](backtest_v2_funding_cap.py), [`results/round2_funding_cap.csv`](results/round2_funding_cap.csv)). Before adding a capped unit, the last settled 8h funding rate is compared with its rolling percentile over the previous 365 days (current settlement excluded, no look-ahead); above it, the unit and any later unit are not added for that trade. Four variants: p90 or p95, on unit 4 only or on units 3 and 4. The cap is rare: the rolling p90 often sits exactly at Binance's 0.01% baseline, so only 3–5% of settlements are above it, and none of P1's 36 unit-3/4 additions happened above it. P1 is therefore identical to v2, and all activations fall in 2024 (3–5 trades, 3–9 units not added). The blocked units would have paid $136–315 of funding, and most capped trades were losers anyway (the cap trims 0.1–0.9R off each loss). But one of them is the +26.5R winner of 26 Feb 2024, which falls to +20.3R (unit-4 cap) or +13.8R (units 3+4), and that single trade outweighs all the savings: full-period return drops to +506–556% (v2 +610%) and P2 Calmar to 0.72–0.81 (v2 0.92). **All four variants (2a–2d) are REJECTED on criterion (a)**: P1 Calmar is equal, not better, and P2 is worse. (b) passes (100% of trades) and so does (c): extreme positive funding marks crowded leveraged longs, raising squeeze risk and carry cost when the pyramid adds its largest exposure.
