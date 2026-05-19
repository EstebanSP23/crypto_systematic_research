# Bull Spring — Long Compression Breakout with BBWP Exit — Killed

**Verdict:** 🚨 Lost money in all tested variants.

---

## 1. Hypothesis

Like Setup A (Spring), but with an explicit "exit when volatility expands" rule instead of relying on a trailing stop. The thesis: enter long when BBWP is compressed and price breaks out, then exit at the first sign of volatility expansion (BBWP > 80) on the assumption that the easy move is complete.

This should produce a high win rate on small wins, with stop losses bounded at 5% of entry.

## 2. Strategy Specification

- **Asset:** BTC, 4H
- **Entry:** BBWP compression + breakout above 20-bar high
- **Stop:** 5% below entry (fixed)
- **Exit:** First close with BBWP > 80
- **Two risk variants tested:** 2% risk per trade, 5% risk per trade

## 3. Backtest Results

| Variant | Trades | WR% | Avg Win | Avg Loss | Final | Return | APY | Max DD |
|---|---|---|---|---|---|---|---|---|
| V1 — 2% risk | 73 | 46.6% | +2.05% | -1.83% | $1,730 | -5.9% | -1.5% | -17.7% |
| V2 — 5% risk | 73 | 46.6% | +5.13% | -4.58% | $1,490 | -19.0% | **-4.9%** | **-40.2%** |

Period: Jan 2022 – May 2026 (~4.4 years). Starting $1,839.

Exit reason breakdown shows the structural problem:
- 45 trades exited at BBWP > 80: 75.6% win rate, average +1.23%
- 28 trades hit the 5% stop loss: 0% win rate, average -2.04%

## 4. Why It Was Killed

The exit rule (BBWP > 80) is **too early** — it cuts winners at small profits while losers run to the full 5% stop. Look at the asymmetry:

- Avg winning exit: **+1.23%** (BBWP-triggered, cuts before the trend completes)
- Avg losing exit: **-2.04%** (full stop-out)

You win 75% of the BBWP exits but each one is tiny. You lose 100% of the stop-outs and each one is twice the size of an average win. Net result: lost money in both variants.

This is the **opposite asymmetry** of a successful trend follower (which has small frequent losses and rare large wins). Bull Spring inverts that into small frequent wins and meaningful occasional losses — which is mathematically guaranteed to lose money unless your win rate is very high.

## 5. The Lesson

**Exit rules matter as much as entry rules.** A great entry with the wrong exit produces a losing strategy. Specifically:

- "Take profit early" rules are seductive (high win rate feels good)
- But they invert the natural asymmetry of trend strategies
- The only mathematically robust trend exit is some variant of "let winners run with a trailing stop"

Bull Spring failed not because the entry signal was bad — the entries showed positive average movement. It failed because the exit cut wins too early to compensate for losers.

## 6. Files

- Source script: `backtest_bullspring.py`
- Chart: `bullspring.png`
