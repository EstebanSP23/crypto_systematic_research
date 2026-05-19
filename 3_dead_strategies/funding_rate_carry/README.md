# Funding Rate Carry — Killed

**Verdict:** ⚠️ Best variant +3.13% APY — about half of USDT lending (6%). Inferior to the no-effort alternative.

---

## 1. Hypothesis

In crypto perpetual futures, the "funding rate" is a periodic payment between long and short holders, designed to keep perp prices anchored to spot. When the rate is positive (the common case in bull markets), shorts receive funding from longs. A market-neutral position — long spot + short perp — collects the funding payment with no directional exposure.

The thesis: collect funding when annualized rates are attractive (>10%), step aside when rates are low or negative. Should produce a steady risk-premium return uncorrelated with directional crypto strategies.

## 2. Strategy Specification

- **Asset:** BTC/USDT
- **Structure:** market-neutral (long spot + short perp on equal notional)
- **Funding events:** every 8 hours (3 per day)
- **Variants tested:**
  - A — Continuous (always hold position)
  - B — Mild threshold (enter when funding > 0.01%/8h, exit when < 0.005%/8h)
  - C — Spike harvest (enter > 0.03%/8h, exit < 0.01%/8h)
  - D — Extreme spikes only (enter > 0.05%/8h, exit < 0.01%/8h)

## 3. Backtest Results

| Variant | Final | Total Return | APY | Funding Earned |
|---|---|---|---|---|
| USDT lending baseline (6%) | $650 | +30.1% | **+6.00%** | n/a |
| A — Continuous | $572 | +14.5% | **+3.13%** | $73 |
| B — Mild threshold | $525 | +5.0% | +1.13% | $30 |
| C — Spike harvest | $519 | +3.9% | +0.87% | $23 |
| D — Extreme spikes only | $512 | +2.5% | +0.56% | $15 |

Period: Jan 2022 – May 2026 (~4.4 years). Starting $500 allocated (smaller test allocation).

Funding rate distribution over the test period:
- Mean: 0.0061% per 8h (~6.7% annualized gross)
- 83.9% of events positive
- Only 5.9% of events exceeded 0.01% per 8h

## 4. Why It Was Killed

**Gross funding (~6.7% annualized) sounds attractive, but it gets consumed by fees on entry/exit and by the basis between spot and perp.** Net of all costs, the continuous variant produces +3.13% APY — about half the risk-free USDT lending baseline.

The threshold variants were intended to be *smarter* — only carry when funding is meaningfully positive — but they end up worse. The reason: each entry/exit cycle pays fees, and the strategy enters/exits more often without the funding rates being high enough to justify the friction.

## 5. The Lesson

**The capacity at retail size matters.** A market-neutral funding-rate strategy actually does generate real returns at institutional scale where fees are negligible. At retail fee levels (0.10% per leg, applied to two legs spot+perp), the structure barely breaks the lending benchmark.

Also: **counterparty risk and operational complexity** matter. Running a market-neutral spot+perp setup requires two separate exchange accounts (or a unified spot+derivatives venue), balancing both legs, monitoring funding, and handling settlement. For an extra ~0% net APY over lending, that complexity is not justified.

This strategy might be revisitable at larger capital ($50k+) or with negotiated fee discounts, but at retail size it is dominated by the simpler alternative of USDT lending.

## 6. Files

- Source script: `backtest_funding_carry.py`
