# 6 — Archive

## Purpose

This folder holds research that predates the validation methodology used in `2_strategies/` and `3_dead_strategies/`. It is kept for provenance, not as a result. Nothing here was run through walk-forward validation or a sensitivity grid, and — critically — **none of it models trading fees**.

It is separated from the kill list deliberately. `3_dead_strategies/` documents strategies that were killed *by* the methodology. This folder holds work that came *before* the methodology existed.

---

## What Is Here: PMARP + BBWP Compression Long on BTC 1H

The project's first strategy, inherited from the TradingView indicator work that preceded this repository.

### Hypothesis

A long entry is high-probability when four independent signals align: the short-term trend is up, price is unusually *close* to its own moving average (PMARP low — no chasing), volatility is compressed and still contracting (BBWP low and falling), and there is a confirmed swing low below price to anchor the stop. Exit when price becomes statistically extended (PMARP high).

### Specification

- **Asset / timeframe:** BTC/USDT, 1H
- **Entry** (all conditions on the same bar, fill at next bar's open):
  - EMA 21 > EMA 55 (1H trend)
  - PMARP < 18 — price near its EMA 13, measured as a 300-bar percentile
  - BBWP < 80 — Bollinger Band Width Percentile, 13-bar basis, 252-bar lookback
  - BBWP 5-bar SMA falling vs. prior bar (volatility still contracting)
  - A confirmed LuxAlgo-style pivot low (15/15, forward-shifted) sits below the close
- **Stop:** the pivot low itself (structural, not volatility-based)
- **Take profit:** first close with PMARP > 77
- **Risk:** 2% per trade, 5% account hard stop, 20× leverage cap
- **Variants:** V1 is 1H only; V2 adds a 4H EMA 21 > EMA 55 trend gate

### Backtest Results (gross, no fees)

| Variant | Trades | WR% | Expectancy | Final | Return | APY | Max DD |
|---|---|---|---|---|---|---|---|
| V1 — 1H only | 269 | 63.9% | +0.052R | $2,345 | +27.5% | +5.9% | -19.9% |
| V2 — 1H + 4H gate | 222 | 64.9% | +0.061R | $2,341 | +27.3% | +5.8% | -16.3% |

Period: Feb 2022 – May 2026 (4.3 years). Starting $1,839. Median hold: 12-13 hours.

Exit breakdown for V1: 200 take-profit, 64 stop-loss, 5 hard-stop. The high win rate comes from the structure of the exit rule, not from an edge — winners are capped at +0.52R average while losers run to -0.78R average.

---

## Why It Is Archived

### 1. The backtests do not model fees, and fees invert the result

Every other backtest in this repository charges 0.10% per leg. These two do not. Adding realistic fees is not a haircut here — it flips the sign:

| Variant | Gross expectancy | Fee cost @ 0.10%/leg | **Net expectancy** |
|---|---|---|---|
| V1 | +0.052R | -0.106R | **-0.054R** |
| V2 | +0.061R | -0.103R | **-0.042R** |

Because the strategy risks 2% on a stop placed at a nearby swing low, position notional runs at roughly 1× the account, so a 0.20% round-trip costs about 0.11R per trade. The gross edge is half that. Over 269 trades the cumulative drag is on the order of 50-60% of the account against a +27.5% gross return.

This is the same **fee drag** failure mode documented in `3_dead_strategies/setup_a_1h_pyramid/` and `counterpunch/` — a small per-trade edge on a fast timeframe, annihilated by friction. The difference is that those strategies were *measured* net of fees and killed on the evidence. This one was never measured at all.

### 2. It was never walk-forward validated

No P1/P2 split, no sensitivity grid. The reported numbers are a single in-sample pass over the full history. Under the standard in `4_methodology/`, that is not a result — it is a hypothesis with a chart attached.

### 3. The indicator stack does not survive its own premise

A 63.9% win rate with negative net expectancy is the clearest illustration in this repository of why win rate is not edge. The PMARP > 77 exit does exactly what the Bull Spring BBWP exit does (see `3_dead_strategies/bull_spring/`): it cuts winners early and lets losers reach a full structural stop, producing the inverted payoff asymmetry that trend-following exists to avoid.

---

## Files

| File | Role |
|---|---|
| `backtest.py` | V1 — 1H only. Writes `backtest_results.csv` |
| `backtest_v2.py` | V2 — adds the 4H trend gate. Writes `backtest_v2_results.csv` |
| `backtest_results.csv` | V1 trade log (269 trades) |
| `backtest_v2_results.csv` | V2 trade log (222 trades) |
| `validate_pmarp.py` | Reproduces the TradingView PMARP indicator in Python (EMA 13, 300-bar lookback) and checks it against the platform's values |
| `validate_bbwp.py` | Same for BBWP (SMA basis 13, lookback 252, MA SMA 5) |
| `analyze.py` | Ad-hoc stats over `backtest_results.csv` — R distribution, exit-reason breakdown, per-year |
| `check_candle.py` | One-off PMARP spot check on live candles |

The two `validate_*.py` scripts are the most reusable thing in this folder: they are standalone, auditable Python reimplementations of two TradingView indicators, verified against the platform before any strategy was built on them. That verification step is the part of this work that was done right.

---

## What This Folder Demonstrates

The methodology in `4_methodology/` was not assumed at the start of this project — it was arrived at. This is what the research looked like before fee modeling and walk-forward splits became non-negotiable, and it is retained so that the difference is visible rather than quietly edited out of the record.
