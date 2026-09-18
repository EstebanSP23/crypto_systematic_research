"""
SETUP A v3 — Curated 4H + BTC daily regime filter.
Compares: WITHOUT regime filter vs WITH regime filter.

Regime filter (when active, allow entries):
  - Daily BTC close > daily 200 EMA  AND
  - Daily BTC 200 EMA > daily 200 EMA from 20 days ago (rising)

When regime is OFF, no new entries allowed.
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
SCORE_THRESHOLD = 8
FEE_PER_LEG     = 0.0010

exchange = ccxt.binance()
since = exchange.parse8601('2023-01-01T00:00:00Z')
since_d_btc = exchange.parse8601('2022-01-01T00:00:00Z')   # earlier for 200 EMA warmup

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
data = {}
for asset in ASSETS:
    raw = fetch_full(asset, '4h', since, exchange)
    if not raw or len(raw) < 220: continue
    df = pd.DataFrame(raw, columns=['ts','open','high','low','close','volume'])
    df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
    df = df.set_index('dt').drop(columns='ts').sort_index()
    df = df[~df.index.duplicated(keep='last')]
    data[asset] = df

print("Fetching daily BTC for regime filter...")
raw_btc_d = fetch_full('BTC/USDT', '1d', since_d_btc, exchange)
df_btc_d = pd.DataFrame(raw_btc_d, columns=['ts','open','high','low','close','volume'])
df_btc_d['dt'] = pd.to_datetime(df_btc_d['ts'], unit='ms', utc=True)
df_btc_d = df_btc_d.set_index('dt').drop(columns='ts')

# Daily BTC 200 EMA + slope
df_btc_d['ema200']     = df_btc_d['close'].ewm(span=200, adjust=False).mean()
df_btc_d['ema200_20d'] = df_btc_d['ema200'].shift(20)
df_btc_d['regime_on']  = (df_btc_d['close'] > df_btc_d['ema200']) & (df_btc_d['ema200'] > df_btc_d['ema200_20d'])
print(f"  Loaded daily BTC ({len(df_btc_d)} bars). Regime ON {df_btc_d['regime_on'].mean()*100:.1f}% of days.")

# Align daily regime to 4H index. Daily bar available after next day starts (24h shift)
df_regime = df_btc_d[['regime_on']].copy()
df_regime.index = df_regime.index + pd.Timedelta(days=1)

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
    # Align daily regime
    aligned = df_regime.reindex(df.index, method='ffill')
    df['regime_on'] = aligned['regime_on'].fillna(False)
    return df

print("Computing indicators...")
for asset in list(data.keys()):
    data[asset] = compute_indicators(data[asset])

def score_setup(df, i):
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

def run(use_regime_filter):
    all_dates = sorted(set().union(*[df.index for df in data.values()]))
    account = INITIAL_CAPITAL
    positions = {}; trades = []; eq = []
    for date in all_dates:
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
                    'score': pos['score'], 'account': account})
                del positions[sym]; continue
            if not pos.get('scaled_out') and high >= pos['first_target']:
                partial_size = pos['size'] * 0.5
                partial_pnl_net = (pos['first_target'] - pos['entry_price']) * partial_size - pos['first_target']*partial_size*FEE_PER_LEG
                account += partial_pnl_net
                pos['partial_pnl_net'] = pos.get('partial_pnl_net', 0) + partial_pnl_net
                pos['size_remaining'] = 0.5
                pos['stop_price'] = pos['entry_price']
                pos['scaled_out'] = True
            if pos.get('scaled_out'):
                low_8 = df['low'].iloc[max(0, idx-8):idx].min()
                ema20 = df['ema20'].iloc[idx]
                trailing = max(low_8, ema20) if not pd.isna(ema20) else low_8
                if trailing > pos['stop_price']: pos['stop_price'] = trailing

        if len(positions) < MAX_POSITIONS:
            candidates = []
            for sym, df in data.items():
                if sym in positions or date not in df.index: continue
                idx = df.index.get_loc(date)
                # REGIME FILTER
                if use_regime_filter:
                    if not bool(df['regime_on'].iloc[idx]):
                        continue
                sc = score_setup(df, idx)
                if sc >= SCORE_THRESHOLD:
                    candidates.append((sym, idx, sc))
            candidates.sort(key=lambda x: -x[2])
            for sym, idx, sc in candidates:
                if len(positions) >= MAX_POSITIONS: break
                df = data[sym]
                if idx + 1 >= len(df): continue
                entry_price = df['open'].iloc[idx+1]
                atr = df['atr14'].iloc[idx]
                consol_low = df['low_14'].iloc[idx]
                stop_price = max(entry_price - 2*atr, consol_low) if not pd.isna(consol_low) else entry_price - 2*atr
                if stop_price >= entry_price or pd.isna(stop_price): continue
                size = (account * RISK_PCT) / (entry_price - stop_price)
                entry_fee = entry_price * size * FEE_PER_LEG
                account -= entry_fee
                positions[sym] = {'entry_date': df.index[idx+1], 'entry_price': entry_price,
                    'stop_price': stop_price, 'first_target': entry_price + 2*(entry_price-stop_price),
                    'size': size, 'size_remaining': 1.0, 'acct_at_entry': account + entry_fee,
                    'score': sc, 'partial_pnl_net': -entry_fee}
        eq.append({'date': date, 'equity': account})
    for sym, pos in positions.items():
        df = data[sym]
        last_close = df['close'].iloc[-1]
        size = pos['size'] * pos['size_remaining']
        exit_pnl = (last_close - pos['entry_price']) * size - last_close*size*FEE_PER_LEG
        total_pnl = exit_pnl + pos.get('partial_pnl_net', 0)
        account += exit_pnl
        trades.append({'symbol': sym, 'entry_date': pos['entry_date'], 'exit_date': data[sym].index[-1],
            'entry_price': pos['entry_price'], 'exit_price': last_close,
            'pnl_usd': total_pnl, 'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
            'exit_reason': 'open_at_end',
            'duration_h': (data[sym].index[-1] - pos['entry_date']).total_seconds()/3600,
            'score': pos['score'], 'account': account})
    return pd.DataFrame(trades), account, pd.DataFrame(eq).set_index('date')

print("\nRunning WITHOUT regime filter (baseline)...")
r_off, final_off, eq_off = run(False)
print(f"  {len(r_off)} trades, final ${final_off:,.2f}")

print("Running WITH BTC daily regime filter...")
r_on, final_on, eq_on = run(True)
print(f"  {len(r_on)} trades, final ${final_on:,.2f}")

def stats(r, final, eq):
    if len(r) == 0:
        return None
    r['win'] = r['R'] > 0
    r['entry_date'] = pd.to_datetime(r['entry_date'])
    r['exit_date'] = pd.to_datetime(r['exit_date'])
    r['year'] = r['exit_date'].dt.year
    wins, losses = r[r['win']], r[~r['win']]
    peak = INITIAL_CAPITAL; mdd = 0
    for v in [INITIAL_CAPITAL] + list(eq['equity']):
        if v > peak: peak = v
        d = (v-peak)/peak*100
        if d < mdd: mdd = d
    days = (eq.index[-1] - eq.index[0]).days
    apy = ((final/INITIAL_CAPITAL) ** (365/max(days,1)) - 1) * 100
    return {
        'trades': len(r), 'win_rate': len(wins)/len(r)*100,
        'avg_win_R': wins['R'].mean() if len(wins) else 0,
        'avg_loss_R': losses['R'].mean() if len(losses) else 0,
        'exp_R': r['R'].mean(),
        'max_dd': mdd, 'final': final,
        'return_pct': (final/INITIAL_CAPITAL-1)*100,
        'apy': apy, 'days': days, 'r': r,
    }

s_off = stats(r_off, final_off, eq_off)
s_on  = stats(r_on, final_on, eq_on)

sep = "─" * 88
print(f"\n{'═'*88}")
print(f"  SETUP A v3 — CURATED 4H — REGIME FILTER COMPARISON")
print(f"{'═'*88}")
print(f"  {'Metric':<28}{'No regime filter':>22}{'With BTC daily regime':>22}")
print(sep)
print(f"  {'Total trades':<28}{s_off['trades']:>22}{s_on['trades']:>22}")
print(f"  {'Win rate %':<28}{s_off['win_rate']:>22.1f}{s_on['win_rate']:>22.1f}")
print(f"  {'Avg win (R)':<28}{s_off['avg_win_R']:>+22.2f}{s_on['avg_win_R']:>+22.2f}")
print(f"  {'Avg loss (R)':<28}{s_off['avg_loss_R']:>+22.2f}{s_on['avg_loss_R']:>+22.2f}")
print(f"  {'Expectancy (R)':<28}{s_off['exp_R']:>+22.3f}{s_on['exp_R']:>+22.3f}")
print(f"  {'Max drawdown %':<28}{s_off['max_dd']:>+22.2f}{s_on['max_dd']:>+22.2f}")
print(f"  {'Final balance ($)':<28}{s_off['final']:>22,.2f}{s_on['final']:>22,.2f}")
print(f"  {'Total return %':<28}{s_off['return_pct']:>+22.1f}{s_on['return_pct']:>+22.1f}")
print(f"  {'APY %':<28}{s_off['apy']:>+22.1f}{s_on['apy']:>+22.1f}")

for label, s in [('NO REGIME FILTER', s_off), ('WITH REGIME FILTER', s_on)]:
    print(f"\n{sep}\n  {label} — YEAR-BY-YEAR")
    print(sep)
    print(f"  {'Year':<8}{'Trades':>8}{'Win%':>8}{'Avg R':>10}{'P&L $':>12}")
    for yr, grp in s['r'].groupby('year'):
        wr = len(grp[grp['win']])/len(grp)*100
        print(f"  {yr:<8}{len(grp):>8}{wr:>7.1f}%{grp['R'].mean():>+10.2f}{grp['pnl_usd'].sum():>+12,.2f}")
    print(f"\n  Per-asset:")
    for sym, grp in s['r'].groupby('symbol'):
        wr = len(grp[grp['win']])/len(grp)*100
        print(f"    {sym:<12} {len(grp):>3} trades  {wr:>5.1f}% win  +{grp['R'].mean():+.2f}R  ${grp['pnl_usd'].sum():+,.2f}")

# Chart
fig, ax = plt.subplots(figsize=(15, 7))
ax.plot(eq_off.index, eq_off['equity'], color='#1f77b4', linewidth=1.4, alpha=0.7,
        label=f"No regime filter  ({s_off['return_pct']:+.0f}%, {s_off['apy']:+.1f}% APY, DD {s_off['max_dd']:.0f}%, {s_off['trades']} trades)")
ax.plot(eq_on.index, eq_on['equity'], color='#d62728', linewidth=1.8,
        label=f"With BTC daily regime  ({s_on['return_pct']:+.0f}%, {s_on['apy']:+.1f}% APY, DD {s_on['max_dd']:.0f}%, {s_on['trades']} trades)")
ax.axhline(INITIAL_CAPITAL, color='gray', linestyle='--', alpha=0.5)
days_idx = (eq_off.index - eq_off.index[0]).days
lending = INITIAL_CAPITAL * (1 + 0.06/365) ** days_idx
ax.plot(eq_off.index, lending, '--', color='green', alpha=0.5, label='USDT lending 6% APY')
ax.set_ylabel('Account ($)')
ax.set_title('Setup A Curated 4H — Regime Filter Comparison', fontweight='bold')
ax.legend(loc='upper left')
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
plt.tight_layout()
plt.savefig('setupA_regime.png', dpi=120, bbox_inches='tight')
print(f"\nChart -> setupA_regime.png")
