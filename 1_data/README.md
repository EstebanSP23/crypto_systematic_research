# 1 — Data Layer

## Purpose

The data layer provides raw OHLCV (Open-High-Low-Close-Volume) market data to all downstream strategy backtests. Data is sourced from public exchange APIs, cached locally, and shared across all strategy modules so backtests are reproducible and avoid redundant API calls.

## Source

- **Primary exchange:** Binance (spot OHLCV)
- **Secondary exchange:** BloFin (perpetual futures, used in live deployment but not in research backtests)
- **Client library:** [CCXT](https://github.com/ccxt/ccxt) (unified Python crypto exchange API)

## Coverage

| Asset | Timeframe | Date Range | Bars (approx) |
|---|---|---|---|
| BTC | 1D | 2017-08 to 2026-05 | ~3,200 |
| BTC | 4H | 2021-01 to 2026-05 | ~11,800 |
| ETH | 4H | 2021-01 to 2026-05 | ~11,800 |
| SOL, LINK, ADA | 4H | 2021-01 to 2026-05 | ~11,800 each |
| ARB | 4H | 2023-03 to 2026-05 | ~6,900 |
| SUI | 4H | 2023-05 to 2026-05 | ~6,700 |
| SEI | 4H | 2023-08 to 2026-05 | ~6,000 |

The variation in altcoin bar counts reflects actual exchange listing dates — a real-world constraint that affects multi-asset strategy design.

## Cache Strategy

Raw data is cached as Python pickle files (`*.pkl`) on first fetch. Subsequent backtests load from cache in milliseconds rather than re-fetching over the network. Cache files are excluded from version control via `.gitignore` (they are ~10-50 MB each).

To regenerate the cache, delete the pickle files and re-run any strategy backtest — it will detect missing data and re-fetch.

## Fetch Function

All strategies use a shared helper pattern:

```python
def fetch_full(symbol, timeframe, since_ms, exchange):
    """Paginated CCXT fetch — handles 1000-bar API limits transparently."""
    out = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
        if not batch: break
        out.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(batch) < 1000: break
    return out
```

The function paginates through CCXT's 1000-bar fetch limit, returning the full available history for the given asset and timeframe.

## Data Limitations (Acknowledged)

- **No tick-level data** — backtests use bar-level OHLCV, which is sufficient for swing/position strategies but inadequate for high-frequency analysis
- **No order book / depth data** — slippage is modeled as zero, which is reasonable at small account sizes on major assets but understates real-world cost at larger sizes
- **Spot vs perpetual divergence** — research backtests use spot OHLCV; live deployment uses perpetuals. Funding rate differences are not modeled in backtests
- **Survivorship in the asset universe** — the multi-asset universe was chosen based on assets that exist today; assets that delisted are not included (acknowledged bias)

These limitations are documented honestly because **acknowledging what a backtest cannot tell you is part of analytical rigor**.
