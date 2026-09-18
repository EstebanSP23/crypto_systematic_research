"""
FUNDING RATE CARRY backtest.

Strategy: LONG spot + SHORT perp = delta-neutral. Earn funding rate every 8h.

We test three variants:
  A) Continuous: hold the carry position the entire 4.5 years
  B) Threshold > 0.01% per 8h: enter when funding decent, exit when low
  C) Threshold > 0.03% per 8h: only harvest big spikes

For each we report: total funding $$ earned, annualized return,
and compare against USDT lending baseline (6% APY).

Assumptions:
  - $500 capital total → $250 spot + $250 perp position
  - Position notional = $500 (the perp short)
  - Maker fees: 0.02% perp, 0.10% spot. Taker fees: 0.05% perp, 0.10% spot.
  - We use taker fees conservatively: 0.30% round-trip total cost per cycle
  - We backtest using BINANCE funding rates (BloFin is mostly perps; for spot leg
    you'd use Binance or similar)
"""
import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ── DATA: fetch historical funding rates from Binance ────────────────────────

exchange = ccxt.binance()
print("Fetching BTC/USDT perpetual funding rate history...")

since = exchange.parse8601('2022-01-01T00:00:00Z')
all_rates = []
batch_count = 0
while True:
    try:
        rates = exchange.fetch_funding_rate_history('BTC/USDT:USDT', since=since, limit=1000)
        batch_count += 1
        if not rates:
            break
        all_rates.extend(rates)
        since = rates[-1]['timestamp'] + 1
        if len(rates) < 1000:
            break
    except Exception as e:
        print(f"  fetch error: {e}")
        break

print(f"  Fetched {len(all_rates)} funding rate records in {batch_count} batches")

df = pd.DataFrame(all_rates)
df['dt']         = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
df['rate']       = df['fundingRate'].astype(float)        # decimal, e.g. 0.0001 = 0.01%
df['rate_bps']   = df['rate'] * 10000                     # basis points
df = df.set_index('dt')[['rate', 'rate_bps']].sort_index()
print(f"  Period: {df.index[0].date()} → {df.index[-1].date()}")
print(f"  Funding events per day: ~{len(df) / (df.index[-1] - df.index[0]).days:.2f}")
print(f"  Mean funding rate: {df['rate'].mean()*100:.5f}% per 8h ({df['rate'].mean()*100*3*365:.2f}% annualized)")
print(f"  Median: {df['rate'].median()*100:.5f}% per 8h")
print(f"  Max:    {df['rate'].max()*100:.5f}% per 8h")
print(f"  Min:    {df['rate'].min()*100:.5f}% per 8h")
print(f"  % positive: {(df['rate'] > 0).mean()*100:.1f}%")
print(f"  % >0.01% per 8h: {(df['rate'] > 0.0001).mean()*100:.1f}%")
print(f"  % >0.03% per 8h: {(df['rate'] > 0.0003).mean()*100:.1f}%")
print(f"  % >0.05% per 8h: {(df['rate'] > 0.0005).mean()*100:.1f}%")

# ── SIMULATION SETUP ──────────────────────────────────────────────────────────

INITIAL_CAPITAL    = 500.0       # total capital
SPOT_ALLOCATION    = 0.5         # 50% in spot, 50% as perp margin
PERP_NOTIONAL      = INITIAL_CAPITAL * SPOT_ALLOCATION  # $250 perp short
ROUND_TRIP_FEE_PCT = 0.003       # 0.3% per cycle (entry + exit both legs)

# Baseline: USDT lending at 6% APY (compounded daily)
days = (df.index[-1] - df.index[0]).days
usdt_lending_return_pct = ((1 + 0.06/365) ** days - 1) * 100
usdt_lending_final = INITIAL_CAPITAL * (1 + usdt_lending_return_pct / 100)
print(f"\nBaseline — USDT lending at 6% APY for {days} days:")
print(f"  Final: ${usdt_lending_final:.2f}  ({usdt_lending_return_pct:+.2f}%)")

# ── SIMULATE VARIANTS ────────────────────────────────────────────────────────

def simulate(min_funding_threshold, exit_threshold, name):
    """
    Enter when funding > min_funding_threshold (annualized BPS).
    Exit when funding < exit_threshold.
    Continuous variant: pass min_funding=-inf, exit_threshold=-inf.
    """
    capital = INITIAL_CAPITAL
    in_position = False
    entries = 0
    exits = 0
    total_funding = 0.0
    total_fees = 0.0
    equity_curve = [(df.index[0], capital)]

    for ts, row in df.iterrows():
        funding_rate = row['rate']

        if not in_position:
            # Check if we should enter
            if funding_rate > min_funding_threshold:
                # Pay entry fees
                fee = ROUND_TRIP_FEE_PCT / 2 * PERP_NOTIONAL  # half of round-trip
                capital -= fee
                total_fees += fee
                in_position = True
                entries += 1
        else:
            # We're in position — collect funding
            funding_received = funding_rate * PERP_NOTIONAL
            capital += funding_received
            total_funding += funding_received

            # Check if we should exit
            if funding_rate < exit_threshold:
                fee = ROUND_TRIP_FEE_PCT / 2 * PERP_NOTIONAL
                capital -= fee
                total_fees += fee
                in_position = False
                exits += 1

        equity_curve.append((ts, capital))

    # Close any open position at end
    if in_position:
        fee = ROUND_TRIP_FEE_PCT / 2 * PERP_NOTIONAL
        capital -= fee
        total_fees += fee

    return {
        'name': name,
        'final':         capital,
        'return_pct':    (capital / INITIAL_CAPITAL - 1) * 100,
        'apy':           ((capital / INITIAL_CAPITAL) ** (365 / days) - 1) * 100,
        'entries':       entries,
        'total_funding': total_funding,
        'total_fees':    total_fees,
        'days_in_pos':   sum(1 for r in df['rate'] if not pd.isna(r)) / 3,  # approx
        'curve':         pd.DataFrame(equity_curve, columns=['date', 'capital']).set_index('date'),
    }

print("\nRunning variants...")
print("  A) Continuous (always hold)...")
res_a = simulate(-1.0, -1.0, 'Continuous')

print("  B) Threshold: enter > 0.01%/8h, exit < 0.005%/8h...")
res_b = simulate(0.0001, 0.00005, 'Mild threshold')

print("  C) Threshold: enter > 0.03%/8h, exit < 0.01%/8h...")
res_c = simulate(0.0003, 0.0001, 'Spike harvest')

print("  D) Threshold: enter > 0.05%/8h, exit < 0.01%/8h...")
res_d = simulate(0.0005, 0.0001, 'Extreme spikes only')

# ── REPORT ────────────────────────────────────────────────────────────────────

sep = "─" * 90
print(f"\n{'═'*90}")
print(f"  FUNDING RATE CARRY — BTC/USDT — Jan 2022 → May 2026  (start ${INITIAL_CAPITAL})")
print(f"{'═'*90}")
print(f"  {'Variant':<32}{'Final':>14}{'Return%':>12}{'APY%':>10}{'Entries':>10}{'Funding $':>12}")
print(sep)
def baseline_row():
    print(f"  {'USDT lending (6% APY)':<32}{usdt_lending_final:>14,.2f}{usdt_lending_return_pct:>+12.2f}{6.00:>10.2f}{0:>10}{0:>12,.2f}")
baseline_row()
for r in [res_a, res_b, res_c, res_d]:
    print(f"  {r['name']:<32}{r['final']:>14,.2f}{r['return_pct']:>+12.2f}{r['apy']:>10.2f}{r['entries']:>10}{r['total_funding']:>12,.2f}")

# Year-by-year breakdown for continuous strategy
print(f"\n{sep}")
print(f"  CONTINUOUS CARRY — yearly returns vs baseline")
print(sep)
print(f"  {'Year':<8}{'Funding earned':>18}{'Return %':>12}{'APY':>10}")
curve_a = res_a['curve']
curve_a['year'] = curve_a.index.year
for yr, grp in curve_a.groupby('year'):
    if len(grp) < 2: continue
    start_cap = grp['capital'].iloc[0]
    end_cap   = grp['capital'].iloc[-1]
    yrly_days = (grp.index[-1] - grp.index[0]).days
    yrly_ret  = (end_cap / start_cap - 1) * 100
    yrly_apy  = ((end_cap / start_cap) ** (365 / max(yrly_days, 1)) - 1) * 100 if yrly_days > 0 else 0
    print(f"  {yr:<8}{end_cap - start_cap:>+18,.2f}{yrly_ret:>+12.2f}{yrly_apy:>10.2f}")

# Funding rate distribution
print(f"\n{sep}")
print(f"  FUNDING RATE DISTRIBUTION (per 8h)")
print(sep)
percentiles = [5, 25, 50, 75, 90, 95, 99]
for p in percentiles:
    val = np.percentile(df['rate'] * 100, p)
    print(f"  {p:>3}th percentile: {val:+.5f}%  ({val*3*365:+.2f}% annualized if constant)")

# ── CHART ─────────────────────────────────────────────────────────────────────

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 9), gridspec_kw={'height_ratios':[2,1]}, sharex=True)

baseline_curve = pd.Series(
    [INITIAL_CAPITAL * (1 + 0.06/365) ** (df.index - df.index[0]).days],
    index=df.index
).iloc[0]
ax1.plot(baseline_curve, baseline_curve.values if hasattr(baseline_curve, 'values') else baseline_curve, '--', color='gray', label=f'USDT lending 6% APY  ({usdt_lending_return_pct:+.0f}%)')

ax1.plot(res_a['curve'].index, res_a['curve']['capital'], color='#1f77b4', label=f"Continuous  ({res_a['return_pct']:+.0f}%, {res_a['apy']:.1f}% APY)")
ax1.plot(res_b['curve'].index, res_b['curve']['capital'], color='#2ca02c', label=f"Mild threshold  ({res_b['return_pct']:+.0f}%, {res_b['apy']:.1f}% APY)")
ax1.plot(res_c['curve'].index, res_c['curve']['capital'], color='#ff7f0e', label=f"Spike harvest  ({res_c['return_pct']:+.0f}%, {res_c['apy']:.1f}% APY)")
ax1.plot(res_d['curve'].index, res_d['curve']['capital'], color='#d62728', label=f"Extreme spikes  ({res_d['return_pct']:+.0f}%, {res_d['apy']:.1f}% APY)")
ax1.axhline(INITIAL_CAPITAL, color='black', linestyle=':', alpha=0.3)
ax1.set_ylabel('Capital ($)')
ax1.set_title('Funding Rate Carry — BTC/USDT — Jan 2022 → May 2026', fontweight='bold')
ax1.legend(loc='upper left')
ax1.grid(True, alpha=0.3)

# Funding rate over time
ax2.plot(df.index, df['rate'] * 100, linewidth=0.5, color='#666')
ax2.axhline(0, color='black', linewidth=0.5)
ax2.axhline(0.01, color='green', linestyle=':', alpha=0.5, label='0.01% threshold')
ax2.axhline(0.03, color='orange', linestyle=':', alpha=0.5, label='0.03% threshold')
ax2.axhline(0.05, color='red', linestyle=':', alpha=0.5, label='0.05% threshold')
ax2.set_ylabel('Funding rate (% per 8h)')
ax2.set_xlabel('Date')
ax2.legend(loc='upper right', fontsize=8)
ax2.grid(True, alpha=0.3)
ax2.set_ylim(-0.1, 0.15)

for ax in [ax1, ax2]:
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

plt.tight_layout()
plt.savefig('funding_carry.png', dpi=120, bbox_inches='tight')
print(f"\nChart -> funding_carry.png")
