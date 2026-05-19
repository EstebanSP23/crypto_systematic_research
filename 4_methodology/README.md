# 4 — Methodology

This folder documents the validation framework applied to every strategy in this repository. The methodology is the most transferable asset in the project — the specific strategies will become obsolete, but the validation discipline applies to any analytical problem with noisy data and finite samples.

## Methodology Documents

| File | Purpose |
|---|---|
| `walkforward_validation.md` | How to split training and exam periods to test for real edge |
| `curvefit_detection.md` | Specific patterns that reveal a strategy is fitted to noise, not signal |
| `sensitivity_analysis.md` | How to construct parameter grids and read robustness results |

*(Documents to be added as the repository is built out)*

---

## Core Principles

### 1. Backtest results are evidence, not truth

A positive backtest is a necessary but not sufficient condition for deployment. The job of validation is to challenge the backtest:

- Does it survive on data the strategy never saw?
- Does it work across reasonable parameter variations?
- After realistic fees and slippage, does it still beat the lending benchmark?
- Could the "edge" be explained by survivorship bias in the asset universe?

### 2. Out-of-sample is the only sample that matters

In-sample performance is whatever you want it to be — you can fit any historical curve given enough parameters. The honest forward expectation is **out-of-sample performance after the strategy was finalized**.

The corollary: once you have seen the out-of-sample result, that data is *contaminated*. You cannot tweak the strategy and re-test on the same data without curve-fitting. New tweaks require new out-of-sample data.

### 3. Pick a metric, then defend it

A strategy that "improves" only when you change the metric being optimized is not improving — it is being p-hacked. Choose a metric upfront (typically expectancy R or APY) and stick with it across variations. If you find yourself adjusting metrics to make a strategy look better, the strategy is the problem.

### 4. Robustness > peak performance

A strategy that produces +10% APY across 90% of reasonable parameter combinations is more deployable than one that produces +30% APY in a single magic cell and 0% everywhere else. Forward, you will not hit the magic cell — you will hit the median cell. Plan accordingly.

### 5. Document failures with the same rigor as successes

The kill list in `3_dead_strategies/` exists because rejecting strategies *for documented reasons* prevents repeating the same mistakes. "I tried X and it didn't work, here's why" is the most valuable kind of research note — and the rarest.

---

## The Curve-Fit Detector (Concrete Pattern)

The single most useful diagnostic developed in this project is this:

> **If a "refinement" has near-zero effect on the training period but large effect on the exam period, the refinement is curve-fit.**

Example: removing certain assets from the Apex universe (SUI, SEI, ARB) had:
- Almost no effect on Period 1 (training): +24.2% → +21.9% APY
- Large effect on Period 2 (fresh exam): +6.0% → +11.5% APY

This asymmetry is the smoking gun. A real edge improvement would help both periods proportionally. The asymmetric improvement means the change is fitted to P2 noise, not exploiting a real pattern.

This detector is applied to every refinement proposed across the project.

---

## Walk-Forward Setup Used

Default walk-forward split applied to most strategies:

| Period | Dates | Purpose |
|---|---|---|
| **P1 — Training** | 2022-01-01 to 2023-12-31 | In-sample design and tuning |
| **P2 — Fresh Exam** | 2024-01-01 to 2026-05-31 | Out-of-sample validation |

Both periods include diverse market conditions: P1 covers the 2022 bear and 2023 recovery; P2 covers the 2024 bull and the 2025 choppy/declining period.

A strategy that survives this split with similar (not necessarily equal) expectancy in both halves passes walk-forward. A strategy that has +25% APY in P1 and -10% APY in P2 fails walk-forward — the edge was an artifact of the training period.

---

## Sensitivity Grid Convention

Default sensitivity grid applied to validated strategies:

- **3 axes:** typically lookback period, ATR multiplier (stop distance), volume confirmation multiplier
- **3 values per axis:** typically below-baseline, baseline, above-baseline
- **Total cells:** 27
- **Reported metric:** count of cells with positive out-of-sample (P2) expectancy

A strategy with 25/27 positive P2 cells has a robust edge. A strategy with 6/27 has a fragile or non-existent edge.

---

## Honest Forward Expectation Reporting

For every strategy in `2_strategies/`, the forward expectation is reported as a **range**, anchored to out-of-sample evidence:

- **APY:** typically 0.5x to 0.8x of in-sample APY (in-sample is inflated)
- **Max DD:** typically 1.0x to 1.5x of in-sample max DD (DD is under-reported in finite samples)

This is the opposite of how most strategy marketing works (which inflates APY and ignores DD). The intent is to **describe what would actually happen forward, not what a hopeful retrospect says happened backward**.
