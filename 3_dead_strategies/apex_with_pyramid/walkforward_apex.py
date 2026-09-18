"""
WALK-FORWARD VALIDATION on APEX 90d Pyramid (4H)

Period 1 ("training"):  Jan 2022 - Dec 2023  (the years where we observed the strategy work)
Period 2 ("fresh exam"): Jan 2024 - May 2026  (out-of-sample, what someone starting fresh would have)

If the strategy holds up in Period 2 with similar metrics → real edge.
If it falls apart in Period 2 → was curve-fit to 2023's bull run.

Same exact rules. Same code. Different time windows.
"""
import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ASSETS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'LINK/USDT', 'ADA/USDT', 'SUI/USDT']

INITIAL_CAPITAL  = 1839.17
RISK_PCT         = 0.02
HARD_STOP_PCT    = 0.05
PYRAMID_N_STEP   = 1.0
MAX_UNITS        = 4
MAX_POSITIONS    = 3
MAX_LEVERAGE     = 20
FEE_PER_LEG      = 0.0010
LOOKBACK_BARS    = 540  # 90 days on 4H

exchange = ccxt.binance()
since_full = exchange.parse8601('2021-01-01T00:00:00Z')   # fetch from 2021 for warmup

def fetch_full(symbol, timeframe, since_ms, exchange):
    all_candles = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
        if not batch: break
        all_candles.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(batch) < 1000: break
    return all_candles

print("Fetching 4H data...")
all_data = {}
for asset in ASSETS:
    raw = fetch_full(asset, '4h', since_full, exchange)
    if not raw or len(raw) < 220: continue
    df = pd.DataFrame(raw, columns=['ts','open','high','low','close','volume'])
    df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
    df = df.set_index('dt').drop(columns='ts').sort_index()
    df = df[~df.index.duplicated(keep='last')]
    all_data[asset] = df
    print(f"  {asset}: {len(df)} bars")

def compute_indicators(df):
    df = df.copy()
    df['sma50']  = df['close'].rolling(50).mean()
    df['sma200'] = df['close'].rolling(200).mean()
    prev_close = df['close'].shift(1)
    tr = pd.concat([df['high']-df['low'], (df['high']-prev_close).abs(), (df['low']-prev_close).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()
    df['vol_sma20'] = df['volume'].rolling(20).mean()
    return df

for asset in list(all_data.keys()):
    all_data[asset] = compute_indicators(all_data[asset])

def is_breakout(df, i):
    if i < max(200, LOOKBACK_BARS): return False
    close = df['close'].iloc[i]
    sma50, sma200 = df['sma50'].iloc[i], df['sma200'].iloc[i]
    atr = df['atr14'].iloc[i]
    vol_sma = df['vol_sma20'].iloc[i]
    volume = df['volume'].iloc[i]
    if any(pd.isna(x) for x in [sma50, sma200, atr, vol_sma]): return False
    if not (close > sma50 > sma200): return False
    prev_high = df['high'].iloc[i-LOOKBACK_BARS:i].max()
    if not (close > prev_high): return False
    if not (volume > vol_sma * 1.5): return False
    return True

def run_backtest(data, start_date, end_date):
    """Run Apex 90d pyramid between start_date and end_date. Data includes warmup before start_date."""
    account = INITIAL_CAPITAL
    positions = {}
    trades = []
    eq_history = []

    # Build sorted date list within window
    all_dates = sorted(set().union(*[df.index for df in data.values()]))
    active_dates = [d for d in all_dates if start_date <= d <= end_date]

    for date in active_dates:
        # Manage existing positions
        for sym in list(positions.keys()):
            if date not in data[sym].index: continue
            df = data[sym]
            idx = df.index.get_loc(date)
            high = df['high'].iloc[idx]
            low  = df['low'].iloc[idx]
            close = df['close'].iloc[idx]
            pos = positions[sym]

            total_size = sum(u['size'] for u in pos['units'])
            wavg = sum(u['entry_price']*u['size'] for u in pos['units']) / total_size

            # Hard 5% stop (catastrophe)
            unrealized_low = (low - wavg) * total_size
            if unrealized_low <= -HARD_STOP_PCT * pos['acct_at_entry']:
                target_loss = -HARD_STOP_PCT * pos['acct_at_entry']
                exit_px = wavg + target_loss / total_size
                exit_fee = exit_px * total_size * FEE_PER_LEG
                exit_pnl = (exit_px - wavg) * total_size - exit_fee
                total_pnl = exit_pnl + pos.get('partial_pnl_net', 0)
                account += exit_pnl
                trades.append({'symbol': sym, 'entry_date': pos['entry_date'], 'exit_date': date,
                    'entry_price': pos['original_entry'], 'exit_price': exit_px,
                    'units': len(pos['units']), 'pnl_usd': total_pnl,
                    'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
                    'exit_reason': 'hard_stop_5pct',
                    'duration_h': (date - pos['entry_date']).total_seconds()/3600,
                    'account': account})
                del positions[sym]
                continue

            # Trailing stop
            if low <= pos['common_stop']:
                exit_px = pos['common_stop']
                exit_fee = exit_px * total_size * FEE_PER_LEG
                exit_pnl = (exit_px - wavg) * total_size - exit_fee
                total_pnl = exit_pnl + pos.get('partial_pnl_net', 0)
                account += exit_pnl
                trades.append({'symbol': sym, 'entry_date': pos['entry_date'], 'exit_date': date,
                    'entry_price': pos['original_entry'], 'exit_price': exit_px,
                    'units': len(pos['units']), 'pnl_usd': total_pnl,
                    'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
                    'exit_reason': 'trailing_stop',
                    'duration_h': (date - pos['entry_date']).total_seconds()/3600,
                    'account': account})
                del positions[sym]
                continue

            # Pyramid additions
            while len(pos['units']) < MAX_UNITS:
                next_trigger = pos['original_entry'] + len(pos['units']) * PYRAMID_N_STEP * pos['original_atr']
                if high < next_trigger: break
                unit_entry = next_trigger
                r_amt = pos['acct_at_entry'] * RISK_PCT
                unit_size = r_amt / (2 * pos['original_atr'])
                total_notional = sum(u['size']*close for u in pos['units']) + unit_size*close
                if total_notional / max(account, 1) > MAX_LEVERAGE: break
                entry_fee = unit_entry * unit_size * FEE_PER_LEG
                account -= entry_fee
                pos['partial_pnl_net'] = pos.get('partial_pnl_net', 0) - entry_fee
                pos['units'].append({'entry_price': unit_entry, 'size': unit_size})
                new_stop = unit_entry - 2 * pos['original_atr']
                if new_stop > pos['common_stop']:
                    pos['common_stop'] = new_stop

            # Trail with 20-bar low
            low_20 = df['low'].iloc[max(0, idx-20):idx].min()
            if low_20 > pos['common_stop']:
                pos['common_stop'] = low_20

        # New entries
        if len(positions) < MAX_POSITIONS:
            for sym, df in data.items():
                if sym in positions: continue
                if date not in df.index: continue
                idx = df.index.get_loc(date)
                if not is_breakout(df, idx): continue
                if idx + 1 >= len(df): continue
                entry_price = df['open'].iloc[idx + 1]
                atr = df['atr14'].iloc[idx]
                stop_price = entry_price - 2 * atr
                if stop_price >= entry_price: continue
                r_amt = account * RISK_PCT
                unit_size = r_amt / (entry_price - stop_price)
                if unit_size * entry_price / max(account,1) > MAX_LEVERAGE: continue
                entry_fee = entry_price * unit_size * FEE_PER_LEG
                account -= entry_fee
                positions[sym] = {
                    'entry_date': df.index[idx + 1], 'original_entry': entry_price,
                    'original_atr': atr, 'common_stop': stop_price,
                    'acct_at_entry': account + entry_fee,
                    'units': [{'entry_price': entry_price, 'size': unit_size}],
                    'partial_pnl_net': -entry_fee,
                }
                if len(positions) >= MAX_POSITIONS: break

        eq_history.append({'date': date, 'equity': account})

    # Close open positions at end
    for sym, pos in positions.items():
        df = data[sym]
        last_close = df['close'].loc[:end_date].iloc[-1]
        total_size = sum(u['size'] for u in pos['units'])
        wavg = sum(u['entry_price']*u['size'] for u in pos['units']) / total_size
        exit_fee = last_close * total_size * FEE_PER_LEG
        exit_pnl = (last_close - wavg) * total_size - exit_fee
        total_pnl = exit_pnl + pos.get('partial_pnl_net', 0)
        account += exit_pnl
        trades.append({'symbol': sym, 'entry_date': pos['entry_date'],
            'exit_date': df.loc[:end_date].index[-1],
            'entry_price': pos['original_entry'], 'exit_price': last_close,
            'units': len(pos['units']), 'pnl_usd': total_pnl,
            'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
            'exit_reason': 'open_at_end',
            'duration_h': (df.loc[:end_date].index[-1] - pos['entry_date']).total_seconds()/3600,
            'account': account})

    return pd.DataFrame(trades), account, pd.DataFrame(eq_history).set_index('date')

# Define periods
P1_start = pd.Timestamp('2022-01-01', tz='UTC')
P1_end   = pd.Timestamp('2023-12-31', tz='UTC')
P2_start = pd.Timestamp('2024-01-01', tz='UTC')
P2_end   = pd.Timestamp('2026-05-31', tz='UTC')

print(f"\nRunning Period 1 (training): {P1_start.date()} → {P1_end.date()}...")
r1, final_1, eq_1 = run_backtest(all_data, P1_start, P1_end)
print(f"  {len(r1)} trades, final ${final_1:,.2f}")

print(f"Running Period 2 (fresh exam): {P2_start.date()} → {P2_end.date()}...")
r2, final_2, eq_2 = run_backtest(all_data, P2_start, P2_end)
print(f"  {len(r2)} trades, final ${final_2:,.2f}")

def stats(r, final, eq, label):
    if len(r) == 0:
        return {'label': label, 'trades':0,'wr':0,'aw':0,'al':0,'exp':0,'dd':0,'final':final,'ret':0,'apy':0,'big':0}
    r['win'] = r['R'] > 0
    wins, losses = r[r['win']], r[~r['win']]
    curve = [INITIAL_CAPITAL] + list(eq['equity'])
    peak = INITIAL_CAPITAL; mdd = 0
    for v in curve:
        if v > peak: peak = v
        d = (v-peak)/peak*100
        if d < mdd: mdd = d
    days = (eq.index[-1] - eq.index[0]).days
    apy = ((final/INITIAL_CAPITAL) ** (365/max(days,1)) - 1) * 100
    return {
        'label': label, 'trades': len(r), 'wr': len(wins)/len(r)*100,
        'aw': wins['R'].mean() if len(wins) else 0,
        'al': losses['R'].mean() if len(losses) else 0,
        'exp': r['R'].mean(),
        'big': r['R'].max(),
        'dd': mdd, 'final': final, 'ret': (final/INITIAL_CAPITAL-1)*100, 'apy': apy,
        'days': days,
    }

s1 = stats(r1, final_1, eq_1, "Period 1 (Jan22-Dec23)")
s2 = stats(r2, final_2, eq_2, "Period 2 (Jan24-May26)")

sep = "─" * 100
print(f"\n{'═'*100}")
print(f"  WALK-FORWARD VALIDATION — APEX 90d Pyramid 4H (6-asset curated universe)")
print(f"{'═'*100}")
print(f"  {'Metric':<28}{'Period 1 (training)':>22}{'Period 2 (fresh exam)':>22}{'Verdict':>22}")
print(sep)

def fmt_row(label, v1, v2, fmt='{:>+22.2f}', threshold_warn=None, units=''):
    """If threshold_warn given, compare and produce verdict."""
    v1s = fmt.format(v1) if v1 is not None else f"{'-':>22}"
    v2s = fmt.format(v2) if v2 is not None else f"{'-':>22}"
    verdict = ''
    if threshold_warn and v1 != 0:
        ratio = v2 / v1 if v1 > 0 else (1 if v2 > 0 else -1)
        if ratio < threshold_warn[0]:
            verdict = '🚨 degraded'
        elif ratio > threshold_warn[1]:
            verdict = '✅ improved'
        else:
            verdict = '✅ consistent'
    print(f"  {label:<28}{v1s}{v2s}{verdict:>22}")

print(f"  {'Days':<28}{s1['days']:>22}{s2['days']:>22}")
print(f"  {'Total trades':<28}{s1['trades']:>22}{s2['trades']:>22}")
fmt_row('Win rate %', s1['wr'], s2['wr'], '{:>22.1f}', (0.7, 1.3))
fmt_row('Avg win (R)', s1['aw'], s2['aw'], '{:>+22.2f}', (0.7, 1.3))
fmt_row('Avg loss (R)', s1['al'], s2['al'], '{:>+22.2f}')
fmt_row('Expectancy (R)', s1['exp'], s2['exp'], '{:>+22.3f}', (0.5, 1.5))
fmt_row('Biggest winner (R)', s1['big'], s2['big'], '{:>+22.2f}')
fmt_row('Max drawdown %', s1['dd'], s2['dd'], '{:>+22.2f}')
fmt_row('Final balance ($)', s1['final'], s2['final'], '{:>22,.2f}')
fmt_row('Total return %', s1['ret'], s2['ret'], '{:>+22.1f}')
fmt_row('APY %', s1['apy'], s2['apy'], '{:>+22.1f}', (0.3, 1.5))

# Chart both equity curves on same axes
fig, ax = plt.subplots(figsize=(14, 7))
ax.plot(eq_1.index, eq_1['equity'], color='#1f77b4', linewidth=1.5,
        label=f"Period 1 (training)   $1839 → ${s1['final']:,.0f}   {s1['apy']:+.1f}% APY   DD {s1['dd']:.0f}%")
# Continue period 2 equity but start from $1839 again (fresh)
ax.plot(eq_2.index, eq_2['equity'], color='#d62728', linewidth=1.5,
        label=f"Period 2 (fresh exam)  $1839 → ${s2['final']:,.0f}   {s2['apy']:+.1f}% APY   DD {s2['dd']:.0f}%")
ax.axhline(INITIAL_CAPITAL, color='gray', linestyle='--', alpha=0.5)
ax.set_ylabel('Account ($) — restarts at $1,839 for each period')
ax.set_title('Apex 90d Pyramid — Walk-Forward Validation', fontweight='bold')
ax.legend(loc='upper left')
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
plt.tight_layout()
plt.savefig('walkforward_apex.png', dpi=120, bbox_inches='tight')
print(f"\nChart -> walkforward_apex.png")

# Per-asset comparison
if len(r1) > 0 and len(r2) > 0:
    print(f"\n{sep}\n  PER-ASSET COMPARISON")
    print(sep)
    print(f"  {'Asset':<12}{'P1 trades':>12}{'P1 Exp R':>12}{'P1 P&L $':>14}{'P2 trades':>12}{'P2 Exp R':>12}{'P2 P&L $':>14}")
    all_syms = sorted(set(r1['symbol'].unique()) | set(r2['symbol'].unique()))
    for sym in all_syms:
        g1 = r1[r1['symbol']==sym]
        g2 = r2[r2['symbol']==sym]
        line = f"  {sym:<12}"
        if len(g1) > 0:
            line += f"{len(g1):>12}{g1['R'].mean():>+12.2f}{g1['pnl_usd'].sum():>+14,.2f}"
        else:
            line += f"{0:>12}{'-':>12}{0:>+14,.2f}"
        if len(g2) > 0:
            line += f"{len(g2):>12}{g2['R'].mean():>+12.2f}{g2['pnl_usd'].sum():>+14,.2f}"
        else:
            line += f"{0:>12}{'-':>12}{0:>+14,.2f}"
        print(line)
