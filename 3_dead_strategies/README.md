# 3 — The Kill List

## Why a Kill List

Most retail trading content shows only the strategies that worked. This is **survivorship bias dressed as education**, and it is the single biggest source of bad decisions made by aspiring systematic traders.

This folder documents 8 rejected strategies, each with hypothesis, backtest result, and the specific reason it was killed. The goal is to demonstrate that **rejecting bad ideas with rigor is the analytical skill that separates real research from cherry-picked storytelling**.

In a job interview context: any data analyst can show you a working dashboard. Showing what you killed, and *why*, is far more diagnostic of judgment.

---

## Summary Table

| # | Strategy | Verdict | Trades | Best APY | Max DD | Reason for Kill |
|---|---|---|---|---|---|---|
| 01 | [Apex *with* Pyramid](apex_with_pyramid/) | 🚨 Curve-fit | 30 / 74 | +121.6% / **-0.2%** | -41% / -54% | Walk-forward collapsed: P1 +121.6% APY → P2 -0.2% APY (122-point swing) |
| 02 | [Setup A "Spring"](setup_a_spring/) | ⚠️ No edge | 250 | +6.0% (best variant) | -38.5% | Best variant barely beats lending; -38.5% DD disqualifies; refinements *degraded* performance (curve-fit) |
| 03 | [Bear Edge](bear_edge/) | ⚠️ No edge | 344 | +0.8% | -20.3% | Best variant returns +0.8% APY — 1/7th of lending benchmark |
| 04 | [Counterpunch](counterpunch/) | ⚠️ No edge | 142-283 | +2.2% (best variant) | -9.2% | Best variant +2.2% APY — still less than USDT lending; fees ate the edge |
| 05 | [Bull Spring](bull_spring/) | 🚨 Negative | 73 | **-1.5%** | -17.7% | Exit rule (BBWP > 80) cuts winners too early; structurally inverted risk:reward |
| 06 | [Setup B Pullback](setup_b_pullback/) | 🚨 Drawdown | 339 | +2.8% | **-64.4%** | 4H variant: -64% drawdown disqualifies despite positive return; 1D variant only +2.9% APY |
| 07 | [Funding Rate Carry](funding_rate_carry/) | ⚠️ No edge | continuous | +3.13% | small | Half of USDT lending; fees consume the funding income at retail size |
| 08 | [Setup A on 1H](setup_a_1h_pyramid/) | 🚨 Catastrophic | 904 | **-34.2%** | **-87.2%** | Fee drag annihilation: -75% return on the same signal that worked on 1D |

P1/P2 splits shown for Apex pyramid. Best-variant figures shown where multiple variants were tested.

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
