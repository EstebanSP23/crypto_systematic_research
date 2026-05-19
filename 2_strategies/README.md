# 2 — Validated & Live Strategies

This folder contains the strategies that survived walk-forward validation. Each subfolder is self-contained with its own README, backtest code, and result outputs.

## Strategy Index

| # | Strategy | Status | Asset(s) | Timeframe | Notes |
|---|---|---|---|---|---|
| 01 | Quattro Donchian Pyramid | 🟢 **Live** | BTC | 4H | Deployed on BloFin since May 2026 |
| 02 | Apex (No Pyramid) | 🟡 Validated | 8-asset universe | 4H | Walk-forward + sensitivity verified |
| 03 | 5 EMA + 200 EMA Slope Filter | 🟡 Validated | BTC | 1W | Single-asset trend filter |

## Status Legend

- 🟢 **Live** — running on a real account with real capital
- 🟡 **Validated** — passed walk-forward and sensitivity tests, deployable but not yet live
- 🔴 **Killed** — failed validation, documented in `3_dead_strategies/` for reference

## Common Methodology

All strategies in this folder share a consistent validation pipeline:

1. **Backtest on the full available history** — establishes baseline performance
2. **Walk-forward split** — train period (typically 2022-2023) vs fresh exam (2024-2026)
3. **Sensitivity grid** — test parameter robustness across reasonable variations
4. **Curve-fit detection** — does any "improvement" appear only out-of-sample? (smoking gun)
5. **Honest forward expectation** — APY and DD are reported based on out-of-sample performance, not in-sample peaks

Details of the methodology framework live in `4_methodology/`.

## Position Sizing Convention

| Strategy | Sizing | Rationale |
|---|---|---|
| Quattro | 2% risk per unit, 4-unit pyramid | Donchian breakout with adds at +0.5N |
| Apex | 2% risk per trade, max 3 concurrent | Diversified across asset universe |
| 5 EMA | 100% all-in per signal | Simple long/flat trend filter |

## Deployment Status

Only Quattro is currently live. Apex and the 5 EMA strategy are research-validated and could be deployed on separate sub-accounts. Live deployment decisions consider:

- Capital allocation across the strategy portfolio
- Operational complexity (one bot is easier than three)
- Correlation between strategies (all three are long-biased trend strategies — they are *not* uncorrelated)
- Drawdown tolerance and recovery time
