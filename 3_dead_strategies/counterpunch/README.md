# Counterpunch — 1H Mean Reversion — Killed

**Verdict:** ⚠️ Best variant returns +2.2% APY — well below USDT lending. Other variants lose money.

---

## 1. Hypothesis

When BTC drops sharply on the 1H timeframe (e.g., 2-3 ATRs in a single bar) and then shows a reversal candle (close above the prior bar's close after a deep wick), mean reversion should pull price back toward the local average. A long entry on the reversal with a tight stop and target at the prior swing high should capture small but frequent wins.

Tested with three variants:
- A) No regime filter — trade all conditions
- B) "Quattro off" — only when Quattro is NOT in position (mean reversion when no trend signal)
- C) "Quattro on" — only when Quattro IS in position (mean reversion as a hedge concept)

## 2. Strategy Specification

- **Asset:** BTC, 1H timeframe
- **Entry:** sharp drop followed by reversal candle
- **Stop:** 1R below entry
- **Target:** 1.5R above entry (asymmetric reward intended)

## 3. Backtest Results

| Variant | Trades | WR% | Expectancy | Total Return | APY | Max DD |
|---|---|---|---|---|---|---|
| A — no regime | 283 | 46.6% | -0.082R | -22.5% | **-5.7%** | -25.8% |
| B — Quattro off | 142 | 50.0% | +0.075R | +10.1% | **+2.2%** | -9.2% |
| C — Quattro on | 141 | 43.3% | -0.240R | -29.6% | -12.1% | -29.7% |

Period: Jan 2022 – May 2026 (~4.3 years, except C which ran shorter).

## 4. Why It Was Killed

Even the best variant (B — only when Quattro is flat) produces just **+2.2% APY** — less than half of USDT lending. The variants that don't use the Quattro filter (A and C) actively lose money.

Mean reversion on 1H has a real pattern (variant A's 46.6% win rate is statistically above random), but each per-trade edge is around 1%, and the round-trip fees of 0.20% consume most of it. After fees, expectancy collapses to slightly negative on most variants.

## 5. The Lesson

**Mean reversion edges on liquid intraday timeframes are mostly arbitraged away.** Any pattern that's visible and tradeable at retail fee levels gets traded by market makers and HFT firms with fee structures 10-100× cheaper. By the time the pattern reaches retail levels of statistical significance, it's already worth less than the friction cost.

Additionally: the "use it only when the trend follower is flat" idea (variant B) is the kind of clever portfolio construction that *sounds* good but doesn't justify the operational complexity for a +2.2% APY edge. **Combining two mediocre strategies usually produces one mediocre strategy, not two complementary ones.**

## 6. Files

- Source script: `backtest_counterpunch.py`
- Trade CSVs: `backtest_counterpunch_A_noregime.csv`, `backtest_counterpunch_B_quattro_off.csv`, `backtest_counterpunch_C_quattro_on.csv`
- Chart: `counterpunch_equity.png`
