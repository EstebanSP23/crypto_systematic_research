"""
WALK-FORWARD VALIDATION on TWO strategies:

1. SPRING (Setup A 4H, score >= 8, no pyramid)
2. APEX no-pyramid (Setup C 4H, 180-day high breakout, no pyramid)

Both use:
  - Same 8-asset universe: BTC, ETH, SOL, LINK, ADA, ARB, SUI, SEI
  - 2% risk per trade, max 3 concurrent positions
  - 2R partial scale-out, then trail with 20-bar low
  - 0.10% per-leg fees

Period 1 (training):  Jan 2022 - Dec 2023
Period 2 (fresh exam): Jan 2024 - May 2026
"""
import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ASSETS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'LINK/USDT',
          'ADA/USDT', 'ARB/USDT', 'SUI/USDT', 'SEI/USDT']

INITIAL_CAPITAL = 1839.17
RISK_PCT        = 0.02
MAX_POSITIONS   = 3
FEE_PER_LEG     = 0.0010

exchange = ccxt.binance()
since_full = exchange.parse8601('2021-01-01T00:00:00Z')

def fetch_full(symbol, timeframe, since_ms, exchange):
    all_candles = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
        if not batch: break
        all_candles.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(batch) < 1000: break
    return all_candles

print("Fetching 4H data for 8 assets...")
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
    df['ema20']  = df['close'].ewm(span=20, adjust=False).mean()
    prev_close = df['close'].shift(1)
    tr = pd.concat([df['high']-df['low'], (df['high']-prev_close).abs(), (df['low']-prev_close).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()
    basis = df['close'].rolling(13).mean()
    df['bbw'] = 2 * df['close'].rolling(13).std(ddof=0) / basis
    bbw_arr = df['bbw'].values
    bbwp = np.full(len(df), np.nan)
    for i in range(13, len(df)):
        start = max(13, i - 252)
        h = bbw_arr[start:i]
        valid = h[~np.isnan(h)]
        if len(valid) > 0:
            bbwp[i] = np.sum(valid <= bbw_arr[i]) / len(valid) * 100
    df['bbwp'] = bbwp
    df['vol_sma20'] = df['volume'].rolling(20).mean()
    df['high_20']   = df['high'].rolling(20).max().shift(1)
    df['low_14']    = df['low'].rolling(14).min().shift(1)
    return df

print("Computing indicators...")
for asset in list(all_data.keys()):
    all_data[asset] = compute_indicators(all_data[asset])

# ── SPRING SCORE FUNCTION (Setup A) ──────────────────────────────────────────

def score_spring(df, i):
    if i < 200: return 0
    if pd.isna(df['bbwp'].iloc[i]) or pd.isna(df['sma200'].iloc[i]) or pd.isna(df['high_20'].iloc[i]):
        return 0
    score = 0
    bbwp = df['bbwp'].iloc[i]
    close = df['close'].iloc[i]
    sma50 = df['sma50'].iloc[i]
    sma200 = df['sma200'].iloc[i]
    if bbwp < 30:  score += 1
    if bbwp < 15:  score += 1
    atr_slice = df['atr14'].iloc[i-5:i+1].values
    if not np.isnan(atr_slice).any():
        if all(atr_slice[j] <= atr_slice[j-1] for j in range(1, len(atr_slice))):
            score += 1
    if close > sma50: score += 1
    if sma50 > sma200: score += 1
    if i >= 20 and not pd.isna(df['sma50'].iloc[i-20]):
        if sma50 > df['sma50'].iloc[i-20]: score += 1
    ath = df['high'].iloc[:i+1].max()
    if close / ath > 0.80: score += 1
    if close > df['high_20'].iloc[i]:
        score += 1
        if not pd.isna(df['vol_sma20'].iloc[i]) and df['volume'].iloc[i] > df['vol_sma20'].iloc[i] * 1.5:
            score += 1
        bar_range = df['high'].iloc[i] - df['low'].iloc[i]
        if bar_range > 0 and (close - df['low'].iloc[i]) / bar_range > 0.7:
            score += 1
    return score

# ── APEX SIGNAL FUNCTION (Setup C) ───────────────────────────────────────────

APEX_LOOKBACK = 1080   # 180 days on 4H

def apex_signal(df, i):
    if i < max(200, APEX_LOOKBACK): return False
    close = df['close'].iloc[i]
    sma50, sma200 = df['sma50'].iloc[i], df['sma200'].iloc[i]
    atr = df['atr14'].iloc[i]
    vol_sma = df['vol_sma20'].iloc[i]
    volume = df['volume'].iloc[i]
    if any(pd.isna(x) for x in [sma50, sma200, atr, vol_sma]): return False
    if not (close > sma50 > sma200): return False
    prev_high = df['high'].iloc[i-APEX_LOOKBACK:i].max()
    if not (close > prev_high): return False
    if not (volume > vol_sma * 1.5): return False
    return True

# ── SHARED BACKTEST ENGINE ───────────────────────────────────────────────────

def run_backtest(data, start_date, end_date, strategy):
    """strategy: 'spring' or 'apex'"""
    account = INITIAL_CAPITAL
    positions = {}
    trades = []
    eq_history = []

    all_dates = sorted(set().union(*[df.index for df in data.values()]))
    active_dates = [d for d in all_dates if start_date <= d <= end_date]

    for date in active_dates:
        # Manage open positions
        for sym in list(positions.keys()):
            if date not in data[sym].index: continue
            df = data[sym]
            idx = df.index.get_loc(date)
            high, low = df['high'].iloc[idx], df['low'].iloc[idx]
            pos = positions[sym]

            if low <= pos['stop_price']:
                exit_px = pos['stop_price']
                size = pos['size'] * pos['size_remaining']
                exit_pnl = (exit_px - pos['entry_price']) * size - exit_px * size * FEE_PER_LEG
                total_pnl = exit_pnl + pos.get('partial_pnl_net', 0)
                account += exit_pnl
                trades.append({'symbol': sym, 'entry_date': pos['entry_date'], 'exit_date': date,
                    'entry_price': pos['entry_price'], 'exit_price': exit_px,
                    'pnl_usd': total_pnl, 'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
                    'exit_reason': 'trailing_stop' if pos.get('scaled_out') else 'stop_loss',
                    'duration_h': (date - pos['entry_date']).total_seconds()/3600,
                    'account': account})
                del positions[sym]
                continue

            if not pos.get('scaled_out') and high >= pos['first_target']:
                partial_size = pos['size'] * 0.5
                partial_pnl_net = (pos['first_target'] - pos['entry_price']) * partial_size - pos['first_target']*partial_size*FEE_PER_LEG
                account += partial_pnl_net
                pos['partial_pnl_net'] = pos.get('partial_pnl_net', 0) + partial_pnl_net
                pos['size_remaining'] = 0.5
                pos['stop_price'] = pos['entry_price']
                pos['scaled_out'] = True

            if pos.get('scaled_out'):
                low_20 = df['low'].iloc[max(0, idx-20):idx].min()
                if low_20 > pos['stop_price']:
                    pos['stop_price'] = low_20

        # New entries
        if len(positions) < MAX_POSITIONS:
            candidates = []
            for sym, df in data.items():
                if sym in positions: continue
                if date not in df.index: continue
                idx = df.index.get_loc(date)
                if strategy == 'spring':
                    sc = score_spring(df, idx)
                    if sc >= 8:
                        candidates.append((sym, idx, sc))
                else:
                    if apex_signal(df, idx):
                        candidates.append((sym, idx, 0))
            if strategy == 'spring':
                candidates.sort(key=lambda x: -x[2])
            for sym, idx, sc in candidates:
                if len(positions) >= MAX_POSITIONS: break
                df = data[sym]
                if idx + 1 >= len(df): continue
                entry_price = df['open'].iloc[idx+1]
                atr = df['atr14'].iloc[idx]
                consol_low = df['low_14'].iloc[idx]
                if strategy == 'spring':
                    stop_price = max(entry_price - 2*atr, consol_low) if not pd.isna(consol_low) else entry_price - 2*atr
                else:
                    stop_price = entry_price - 2*atr
                if stop_price >= entry_price or pd.isna(stop_price): continue
                size = (account * RISK_PCT) / (entry_price - stop_price)
                entry_fee = entry_price * size * FEE_PER_LEG
                account -= entry_fee
                positions[sym] = {
                    'entry_date': df.index[idx+1], 'entry_price': entry_price,
                    'stop_price': stop_price,
                    'first_target': entry_price + 2*(entry_price-stop_price),
                    'size': size, 'size_remaining': 1.0, 'acct_at_entry': account + entry_fee,
                    'partial_pnl_net': -entry_fee,
                }

        eq_history.append({'date': date, 'equity': account})

    # Close open at end
    for sym, pos in positions.items():
        df = data[sym]
        last_close = df['close'].loc[:end_date].iloc[-1]
        size = pos['size'] * pos['size_remaining']
        exit_pnl = (last_close - pos['entry_price']) * size - last_close*size*FEE_PER_LEG
        total_pnl = exit_pnl + pos.get('partial_pnl_net', 0)
        account += exit_pnl
        trades.append({'symbol': sym, 'entry_date': pos['entry_date'],
            'exit_date': df.loc[:end_date].index[-1],
            'entry_price': pos['entry_price'], 'exit_price': last_close,
            'pnl_usd': total_pnl, 'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
            'exit_reason': 'open_at_end',
            'duration_h': (df.loc[:end_date].index[-1] - pos['entry_date']).total_seconds()/3600,
            'account': account})

    return pd.DataFrame(trades), account, pd.DataFrame(eq_history).set_index('date')

# Periods
P1_start = pd.Timestamp('2022-01-01', tz='UTC')
P1_end   = pd.Timestamp('2023-12-31', tz='UTC')
P2_start = pd.Timestamp('2024-01-01', tz='UTC')
P2_end   = pd.Timestamp('2026-05-31', tz='UTC')

results = {}
for label, strategy in [('Spring', 'spring'), ('Apex', 'apex')]:
    print(f"\nRunning {label}...")
    print(f"  Period 1 (training): {P1_start.date()} → {P1_end.date()}")
    r1, f1, eq1 = run_backtest(all_data, P1_start, P1_end, strategy)
    print(f"    {len(r1)} trades, final ${f1:,.2f}")
    print(f"  Period 2 (fresh exam): {P2_start.date()} → {P2_end.date()}")
    r2, f2, eq2 = run_backtest(all_data, P2_start, P2_end, strategy)
    print(f"    {len(r2)} trades, final ${f2:,.2f}")
    results[label] = {'P1': (r1, f1, eq1), 'P2': (r2, f2, eq2)}

def stats(r, final, eq):
    if len(r) == 0:
        return {'trades':0,'wr':0,'aw':0,'al':0,'exp':0,'dd':0,'final':final,'ret':0,'apy':0,'big':0}
    r['win'] = r['R'] > 0
    wins, losses = r[r['win']], r[~r['win']]
    curve = [INITIAL_CAPITAL] + list(eq['equity'])
    peak = INITIAL_CAPITAL; mdd = 0
    for v in curve:
        if v > peak: peak = v
        d = (v-peak)/peak*100
        if d < mdd: mdd = d
    days = (eq.index[-1] - eq.index[0]).days if len(eq) > 0 else 1
    apy = ((final/INITIAL_CAPITAL) ** (365/max(days,1)) - 1) * 100
    return {
        'trades': len(r), 'wr': len(wins)/len(r)*100,
        'aw': wins['R'].mean() if len(wins) else 0,
        'al': losses['R'].mean() if len(losses) else 0,
        'exp': r['R'].mean(),
        'big': r['R'].max() if len(r) else 0,
        'dd': mdd, 'final': final, 'ret': (final/INITIAL_CAPITAL-1)*100, 'apy': apy,
    }

sep = "─" * 110
print(f"\n{'═'*110}")
print(f"  WALK-FORWARD VALIDATION — Spring vs Apex no-pyramid (4H, 8-asset universe)")
print(f"{'═'*110}")

for label in ['Spring', 'Apex']:
    r1, f1, eq1 = results[label]['P1']
    r2, f2, eq2 = results[label]['P2']
    s1 = stats(r1, f1, eq1)
    s2 = stats(r2, f2, eq2)

    print(f"\n  ▶ {label}")
    print(sep)
    print(f"  {'Metric':<24}{'P1 (2022-23)':>22}{'P2 (2024-26)':>22}{'Verdict':>32}")
    print(sep)

    def verdict_ratio(a, b, good_band=(0.5, 1.5)):
        if a <= 0 or b is None or a is None: return ''
        r = b / a
        if r < good_band[0]: return '🚨 degraded'
        if r > good_band[1]: return '✅ improved'
        return '✅ consistent'

    def verdict_signs(a, b):
        if a > 0 and b > 0: return '✅ both positive'
        if a < 0 and b < 0: return '⚠️ both negative'
        if a > 0 and b <= 0: return '🚨 reversed (P1+ → P2-)'
        if a <= 0 and b > 0: return '🤔 reversed (P1- → P2+)'
        return ''

    print(f"  {'Trades':<24}{s1['trades']:>22}{s2['trades']:>22}")
    print(f"  {'Win rate %':<24}{s1['wr']:>22.1f}{s2['wr']:>22.1f}{verdict_ratio(s1['wr'], s2['wr'], (0.7, 1.3)):>32}")
    print(f"  {'Avg win (R)':<24}{s1['aw']:>+22.2f}{s2['aw']:>+22.2f}{verdict_ratio(s1['aw'], s2['aw']):>32}")
    print(f"  {'Avg loss (R)':<24}{s1['al']:>+22.2f}{s2['al']:>+22.2f}")
    print(f"  {'Expectancy (R)':<24}{s1['exp']:>+22.3f}{s2['exp']:>+22.3f}{verdict_signs(s1['exp'], s2['exp']):>32}")
    print(f"  {'Biggest winner (R)':<24}{s1['big']:>+22.2f}{s2['big']:>+22.2f}")
    print(f"  {'Max drawdown %':<24}{s1['dd']:>+22.2f}{s2['dd']:>+22.2f}")
    print(f"  {'Final ($)':<24}{s1['final']:>22,.2f}{s2['final']:>22,.2f}")
    print(f"  {'Return %':<24}{s1['ret']:>+22.1f}{s2['ret']:>+22.1f}{verdict_signs(s1['ret'], s2['ret']):>32}")
    print(f"  {'APY %':<24}{s1['apy']:>+22.1f}{s2['apy']:>+22.1f}{verdict_ratio(s1['apy'], s2['apy']):>32}")

# Combined chart
fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=False)
for i, label in enumerate(['Spring', 'Apex']):
    r1, f1, eq1 = results[label]['P1']
    r2, f2, eq2 = results[label]['P2']
    s1 = stats(r1, f1, eq1); s2 = stats(r2, f2, eq2)
    ax = axes[i]
    if len(eq1) > 0:
        ax.plot(eq1.index, eq1['equity'], color='#1f77b4', linewidth=1.5,
                label=f"P1 training:  ${INITIAL_CAPITAL:,.0f} → ${s1['final']:,.0f}  ({s1['apy']:+.1f}% APY, DD {s1['dd']:.0f}%)")
    if len(eq2) > 0:
        ax.plot(eq2.index, eq2['equity'], color='#d62728', linewidth=1.5,
                label=f"P2 fresh exam: ${INITIAL_CAPITAL:,.0f} → ${s2['final']:,.0f}  ({s2['apy']:+.1f}% APY, DD {s2['dd']:.0f}%)")
    ax.axhline(INITIAL_CAPITAL, color='gray', linestyle='--', alpha=0.5)
    ax.set_ylabel('Account ($)')
    ax.set_title(f'{label} — Walk-Forward (resets to $1,839 each period)', fontweight='bold')
    ax.legend(loc='upper left', fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
plt.tight_layout()
plt.savefig('walkforward_spring_apex.png', dpi=120, bbox_inches='tight')
print(f"\nChart -> walkforward_spring_apex.png")
