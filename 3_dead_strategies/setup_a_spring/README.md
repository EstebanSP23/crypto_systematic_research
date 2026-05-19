# Setup A "Spring" — Killed

**Verdict:** ⚠️ No edge worth running. Best variant returns +6.0% APY with -38.5% drawdown — below USDT lending after risk-adjustment.

---

## 1. Hypothesis

When an asset goes through a period of compressed volatility (low Bollinger Band Width Percentile, "BBWP"), it is coiling for a directional move. Combined with a multi-factor scoring system (trend alignment, distance from ATH, breakout strength, volume confirmation), a high-score breakout from compression should identify trades with asymmetric upside.

Tested across multiple variants (original, v2, curated, regime-filtered, sniper) on the 8-asset 4H universe.

## 2. Strategy Specification (Score ≥ 8 threshold)

- **Universe:** BTC, ETH, SOL, LINK, ADA, ARB, SUI, SEI on 4H
- **Score components (each adds 1-2 points):**
  - BBWP < 30 (compressed) and BBWP < 15 (extreme compression)
  - Falling ATR over last 5 bars
  - close > 50 SMA, 50 SMA > 200 SMA, 50 SMA rising
  - close > 80% of ATH
  - close > 20-bar high (breakout)
  - Volume > 1.5× 20-bar avg
  - Strong close (in upper 70% of range)
- **Entry threshold:** total score ≥ 8 of 10
- **Stop:** 2× ATR
- **Exit:** 50% off at 2R, trail with 20-bar low

## 3. Backtest Results

| Variant | Trades | WR% | Expectancy | Return | APY | Max DD |
|---|---|---|---|---|---|---|
| Full (8-asset, score ≥ 8) | 250 | 36.0% | +0.093R | +21.1% | **+6.0%** | -38.5% |
| Curated (filtered scoring) | 205 | 36.1% | +0.044R | +1.4% | +0.4% | -34.1% |

Period: Feb 2023 – May 2026 (~3.3 years). Starting capital $1,839.

## 4. Why It Was Killed

Even the best variant produces only **+6% APY with -38.5% max drawdown** — meaning the risk-adjusted return is barely positive after fees and worse than passive USDT lending at 6% APY *with zero drawdown*.

Worse, the "curated" variant — where I added additional rules to filter out lower-quality signals — produced *worse* results than the unfiltered version (+0.4% APY vs +6.0%). **This is a classic curve-fit signature: tweaking based on observed losers should have improved things if the rules captured a real pattern. Instead, every refinement degraded performance.**

The compression-breakout setup is real and visible in the data, but the magnitude of edge is too small at retail fee levels to be worth running.

## 5. The Lesson

A strategy that beats fees but loses to the lending benchmark is not deployable. **The bar isn't "positive return" — it's "positive return that justifies operational complexity and drawdown risk over the no-effort alternative."**

Also: when refinements *degrade* out-of-sample performance, that is direct evidence the original "edge" was statistical noise, not signal.

## 6. Files

- Source scripts: `backtest_setupA.py`, `backtest_setupA_v2.py`, `backtest_setupA_curated.py` (in research directory)
- Trade CSVs: `setupA_trades_4h.csv`, `setupA_curated_4h_trades.csv`
