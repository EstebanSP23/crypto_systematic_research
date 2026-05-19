# 3 — The Kill List

## Why a Kill List

Most retail trading content shows only the strategies that worked. This is **survivorship bias dressed as education**, and it is the single biggest source of bad decisions made by aspiring systematic traders.

This folder documents 8 rejected strategies, each with hypothesis, backtest result, and the specific reason it was killed. The goal is to demonstrate that **rejecting bad ideas with rigor is the analytical skill that separates real research from cherry-picked storytelling**.

In a job interview context: any data analyst can show you a working dashboard. Showing what you killed, and *why*, is far more diagnostic of judgment.

---

## Summary Table

| # | Strategy | Type | Verdict | Reason for Kill |
|---|---|---|---|---|
| 01 | Apex *with* Pyramid | Trend-following | 🚨 Curve-fit | +122% APY in training collapsed to -0.2% APY out-of-sample — classic 2023-bull-regime over-fit |
| 02 | Setup A "Spring" | Volatility compression breakout | ⚠️ No edge | Score ≥ 8 filter too selective; ~2% APY barely beats fees |
| 03 | Bear Edge | BTC shorts (counter-trend) | ⚠️ No edge | Negative expectancy after fees; structurally hard in crypto |
| 04 | Counterpunch | 1H mean reversion | ⚠️ No edge | Didn't beat USDT lending; fees ate the small edge |
| 05 | Bull Spring | Long compression w/ BBWP exit | 🚨 Negative | Lost money in walk-forward |
| 06 | Setup B Pullback | Pullback to MA in uptrend | 🚨 Drawdown | -64% drawdown disqualified despite positive total return |
| 07 | Funding Rate Carry | Perp funding arb on BTC | ⚠️ No edge | 3% APY, inferior to USDT lending after operational risk |
| 08 | Setup A on 1H | Compression breakout on 1H | 🚨 Negative | Fees destroyed it (-75% total return) |

## Status Legend

- 🚨 **Killed** — strategy explicitly loses money or breaks down out-of-sample
- ⚠️ **No edge** — strategy is roughly break-even or marginal vs lending benchmark, not worth complexity

---

## Common Failure Modes Observed

Across these 8 rejected strategies, three failure modes account for nearly all the kills:

### 1. **Curve-fitting to a favorable regime** (Apex pyramid, Setup A on 1H)
A strategy that looks magical in 2023 (Bitcoin bull market) collapses when applied to 2024-2026. The "edge" was just a tailwind.

**Detection method:** walk-forward split — train on one period, test on another. If the second-period performance is dramatically worse, the strategy was fitted to noise.

### 2. **Fee drag on high-frequency timeframes** (Setup A on 1H, Counterpunch 1H)
A strategy with a small per-trade edge gets destroyed by 0.10% per-leg fees when it trades hundreds of times. Even +0.20R per trade is wiped out if you pay 0.20% round-trip on 50% of the position.

**Detection method:** report per-trade R both gross of fees and net of fees. If net expectancy is < 0.10R per trade, fees will dominate.

### 3. **Drawdown despite positive total return** (Setup B Pullback)
A strategy that ends positive over the test period but goes through -64% drawdown is not deployable. No real human (or risk-managed institution) can sit through that.

**Detection method:** always report max drawdown alongside total return. A strategy with +100% return and -60% DD is worse than one with +40% return and -15% DD.

---

## How to Read Each Sub-Folder

Each rejected strategy has its own folder with:
- `README.md` — hypothesis, spec, backtest result, kill reason
- *(some folders include `notes.md`)* — additional analysis

The detail is intentionally concise. The point is the **reasoning**, not the implementation.

---

## What This Folder Demonstrates

- **Discipline:** the willingness to kill an idea even after investing time in it
- **Methodology:** explicit detection of curve-fit, fee drag, and drawdown risk
- **Honesty:** publishing failures is rare; it costs nothing analytically and pays dividends in credibility
- **Decision quality:** every strategy in `2_strategies/` survived this same gauntlet
