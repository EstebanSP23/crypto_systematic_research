"""
APEX no-pyramid SENSITIVITY GRID

Goal: test whether the edge survives across a band of parameters, NOT pick a "best".

Grid (27 combos):
  - LOOKBACK_BARS: 540 (90d), 1080 (180d, baseline), 2160 (360d)
  - ATR_MULT (stop):   1.5, 2.0 (baseline), 2.5
  - VOL_MULT:          1.0, 1.5 (baseline), 2.0

For each combo, run both P1 (2022-23) and P2 (2024-26). Output: P2 APY heatmap-style table
plus a side-by-side P1/P2 expectancy table. The question we answer:
  - Is the edge present across most of the grid, or only at the baseline?
  - Does any combo flip P2 to negative? (That would mean the edge is fragile.)
"""
import ccxt
import pandas as pd
import numpy as np
import itertools
import json
import os

ASSETS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'LINK/USDT',
          'ADA/USDT', 'ARB/USDT', 'SUI/USDT', 'SEI/USDT']

INITIAL_CAPITAL = 1839.17
RISK_PCT        = 0.02
MAX_POSITIONS   = 3
FEE_PER_LEG     = 0.0010

P1_start = pd.Timestamp('2022-01-01', tz='UTC')
P1_end   = pd.Timestamp('2023-12-31', tz='UTC')
P2_start = pd.Timestamp('2024-01-01', tz='UTC')
P2_end   = pd.Timestamp('2026-05-31', tz='UTC')

CACHE = 'ohlcv_4h_cache.pkl'

def fetch_full(symbol, timeframe, since_ms, exchange):
    all_candles = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
        if not batch: break
        all_candles.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(batch) < 1000: break
    return all_candles

def load_data():
    import pickle
    if os.path.exists(CACHE):
        print(f"Loading cached data from {CACHE}...")
        with open(CACHE, 'rb') as f:
            all_data = pickle.load(f)
        for sym in all_data:
            print(f"  {sym}: {len(all_data[sym])} bars")
        return all_data
    print("Fetching 4H data for 8 assets...")
    exchange = ccxt.binance()
    since = exchange.parse8601('2021-01-01T00:00:00Z')
    all_data = {}
    for asset in ASSETS:
        raw = fetch_full(asset, '4h', since, exchange)
        if not raw or len(raw) < 220: continue
        df = pd.DataFrame(raw, columns=['ts','open','high','low','close','volume'])
        df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
        df = df.set_index('dt').drop(columns='ts').sort_index()
        df = df[~df.index.duplicated(keep='last')]
        all_data[asset] = df
        print(f"  {asset}: {len(df)} bars")
    with open(CACHE, 'wb') as f:
        pickle.dump(all_data, f)
    return all_data

def compute_indicators(df):
    df = df.copy()
    df['sma50']  = df['close'].rolling(50).mean()
    df['sma200'] = df['close'].rolling(200).mean()
    prev_close = df['close'].shift(1)
    tr = pd.concat([df['high']-df['low'], (df['high']-prev_close).abs(), (df['low']-prev_close).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()
    df['vol_sma20'] = df['volume'].rolling(20).mean()
    return df

def apex_signal(df, i, lookback, vol_mult):
    if i < max(200, lookback): return False
    close = df['close'].iloc[i]
    sma50, sma200 = df['sma50'].iloc[i], df['sma200'].iloc[i]
    atr = df['atr14'].iloc[i]
    vol_sma = df['vol_sma20'].iloc[i]
    volume = df['volume'].iloc[i]
    if any(pd.isna(x) for x in [sma50, sma200, atr, vol_sma]): return False
    if not (close > sma50 > sma200): return False
    prev_high = df['high'].iloc[i-lookback:i].max()
    if not (close > prev_high): return False
    if vol_mult > 0 and not (volume > vol_sma * vol_mult): return False
    return True

def run_backtest(data, start_date, end_date, lookback, atr_mult, vol_mult):
    account = INITIAL_CAPITAL
    positions = {}
    trades = []
    eq_history = []

    all_dates = sorted(set().union(*[df.index for df in data.values()]))
    active_dates = [d for d in all_dates if start_date <= d <= end_date]

    for date in active_dates:
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
                trades.append({'symbol': sym, 'pnl_usd': total_pnl,
                    'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT)})
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

        if len(positions) < MAX_POSITIONS:
            for sym, df in data.items():
                if sym in positions: continue
                if date not in df.index: continue
                idx = df.index.get_loc(date)
                if not apex_signal(df, idx, lookback, vol_mult): continue
                if idx + 1 >= len(df): continue
                entry_price = df['open'].iloc[idx + 1]
                atr = df['atr14'].iloc[idx]
                stop_price = entry_price - atr_mult * atr
                if stop_price >= entry_price: continue
                if len(positions) >= MAX_POSITIONS: break
                stop_distance = entry_price - stop_price
                size = (account * RISK_PCT) / stop_distance
                entry_fee = entry_price * size * FEE_PER_LEG
                account -= entry_fee
                positions[sym] = {
                    'entry_date': df.index[idx + 1], 'entry_price': entry_price,
                    'stop_price': stop_price,
                    'first_target': entry_price + 2 * stop_distance,
                    'size': size, 'size_remaining': 1.0,
                    'acct_at_entry': account + entry_fee,
                    'partial_pnl_net': -entry_fee,
                }

        eq_history.append({'date': date, 'equity': account})

    for sym, pos in positions.items():
        df = data[sym]
        last_close = df['close'].loc[:end_date].iloc[-1]
        size = pos['size'] * pos['size_remaining']
        exit_pnl = (last_close - pos['entry_price']) * size - last_close*size*FEE_PER_LEG
        total_pnl = exit_pnl + pos.get('partial_pnl_net', 0)
        account += exit_pnl
        trades.append({'symbol': sym, 'pnl_usd': total_pnl,
            'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT)})

    eq = pd.DataFrame(eq_history).set_index('date') if eq_history else pd.DataFrame()
    return pd.DataFrame(trades), account, eq

def metrics(trades, final, eq, start, end):
    n = len(trades)
    if n == 0:
        return {'trades': 0, 'wr': 0, 'exp': 0, 'final': final, 'apy': 0, 'dd': 0}
    wins = trades[trades['R'] > 0]
    curve = [INITIAL_CAPITAL] + (list(eq['equity']) if len(eq) else [])
    peak, mdd = INITIAL_CAPITAL, 0
    for v in curve:
        if v > peak: peak = v
        d = (v - peak) / peak * 100
        if d < mdd: mdd = d
    days = (end - start).days
    apy = ((final/INITIAL_CAPITAL) ** (365/max(days,1)) - 1) * 100
    return {
        'trades': n, 'wr': len(wins)/n*100,
        'exp': trades['R'].mean(),
        'final': final, 'apy': apy, 'dd': mdd,
    }

def main():
    raw = load_data()
    print("Computing indicators...")
    data = {sym: compute_indicators(df) for sym, df in raw.items()}

    LOOKBACKS = [540, 1080, 2160]   # 90d, 180d (baseline), 360d
    ATR_MULTS = [1.5, 2.0, 2.5]
    VOL_MULTS = [1.0, 1.5, 2.0]

    rows = []
    total = len(LOOKBACKS) * len(ATR_MULTS) * len(VOL_MULTS)
    i = 0
    for lb, am, vm in itertools.product(LOOKBACKS, ATR_MULTS, VOL_MULTS):
        i += 1
        is_baseline = (lb == 1080 and am == 2.0 and vm == 1.5)
        tag = " (baseline)" if is_baseline else ""
        print(f"\n[{i}/{total}] lookback={lb} ({lb*4/24:.0f}d), ATR×{am}, vol×{vm}{tag}")
        t1, f1, e1 = run_backtest(data, P1_start, P1_end, lb, am, vm)
        t2, f2, e2 = run_backtest(data, P2_start, P2_end, lb, am, vm)
        m1 = metrics(t1, f1, e1, P1_start, P1_end)
        m2 = metrics(t2, f2, e2, P2_start, P2_end)
        print(f"   P1: {m1['trades']:>3} trades, {m1['wr']:>5.1f}% win, exp {m1['exp']:+.3f}R, APY {m1['apy']:+6.1f}%, DD {m1['dd']:+6.1f}%")
        print(f"   P2: {m2['trades']:>3} trades, {m2['wr']:>5.1f}% win, exp {m2['exp']:+.3f}R, APY {m2['apy']:+6.1f}%, DD {m2['dd']:+6.1f}%")
        rows.append({
            'lookback': lb, 'atr_mult': am, 'vol_mult': vm,
            'p1_trades': m1['trades'], 'p1_wr': m1['wr'], 'p1_exp': m1['exp'], 'p1_apy': m1['apy'], 'p1_dd': m1['dd'],
            'p2_trades': m2['trades'], 'p2_wr': m2['wr'], 'p2_exp': m2['exp'], 'p2_apy': m2['apy'], 'p2_dd': m2['dd'],
            'baseline': is_baseline,
        })

    df = pd.DataFrame(rows)
    df.to_csv('sensitivity_apex.csv', index=False)
    print("\nSaved -> sensitivity_apex.csv")

    sep = "─" * 110
    print(f"\n{'═'*110}")
    print(f"  APEX SENSITIVITY GRID — 27 combos, walk-forward (P1 2022-23 train / P2 2024-26 fresh exam)")
    print(f"{'═'*110}")
    print(f"  {'lookback':<10}{'ATR×':<6}{'vol×':<6}{'P1 trd':>7}{'P1 exp':>9}{'P1 APY':>9}{'P1 DD':>8}{'P2 trd':>7}{'P2 exp':>9}{'P2 APY':>9}{'P2 DD':>8}")
    print(sep)
    for _, r in df.iterrows():
        flag = " *" if r['baseline'] else "  "
        print(f"  {int(r['lookback']):<10}{r['atr_mult']:<6}{r['vol_mult']:<6}"
              f"{int(r['p1_trades']):>7}{r['p1_exp']:>+9.3f}{r['p1_apy']:>+9.1f}{r['p1_dd']:>+8.1f}"
              f"{int(r['p2_trades']):>7}{r['p2_exp']:>+9.3f}{r['p2_apy']:>+9.1f}{r['p2_dd']:>+8.1f}{flag}")

    print(f"\n{sep}")
    print("  ROBUSTNESS SUMMARY")
    print(sep)
    p2_pos_exp = (df['p2_exp'] > 0).sum()
    p2_pos_apy = (df['p2_apy'] > 0).sum()
    p2_beats_lending = (df['p2_apy'] > 6.0).sum()   # USDT lending ~6% effective
    p1_pos_exp = (df['p1_exp'] > 0).sum()
    print(f"  P1 positive expectancy:  {p1_pos_exp}/{total} configs  ({100*p1_pos_exp/total:.0f}%)")
    print(f"  P2 positive expectancy:  {p2_pos_exp}/{total} configs  ({100*p2_pos_exp/total:.0f}%)")
    print(f"  P2 positive APY:         {p2_pos_apy}/{total} configs  ({100*p2_pos_apy/total:.0f}%)")
    print(f"  P2 beats USDT lending:   {p2_beats_lending}/{total} configs  ({100*p2_beats_lending/total:.0f}%)")
    print(f"  P2 APY range:            {df['p2_apy'].min():+.1f}% to {df['p2_apy'].max():+.1f}%, median {df['p2_apy'].median():+.1f}%")
    print(f"  P2 expectancy range:     {df['p2_exp'].min():+.3f}R to {df['p2_exp'].max():+.3f}R, median {df['p2_exp'].median():+.3f}R")
    print(f"  P2 max DD range:         {df['p2_dd'].min():+.1f}% to {df['p2_dd'].max():+.1f}%, median {df['p2_dd'].median():+.1f}%")

    print(f"\n  TOP-5 by P2 APY (caution: these are noise-inflated, not 'optimal'):")
    top5 = df.sort_values('p2_apy', ascending=False).head(5)
    for _, r in top5.iterrows():
        print(f"    lb={int(r['lookback'])}, ATR×{r['atr_mult']}, vol×{r['vol_mult']}: "
              f"P1 APY {r['p1_apy']:+.1f}% / P2 APY {r['p2_apy']:+.1f}% / P2 DD {r['p2_dd']:+.1f}%")
    print(f"\n  BOTTOM-5 by P2 APY:")
    bot5 = df.sort_values('p2_apy', ascending=True).head(5)
    for _, r in bot5.iterrows():
        print(f"    lb={int(r['lookback'])}, ATR×{r['atr_mult']}, vol×{r['vol_mult']}: "
              f"P1 APY {r['p1_apy']:+.1f}% / P2 APY {r['p2_apy']:+.1f}% / P2 DD {r['p2_dd']:+.1f}%")

if __name__ == '__main__':
    main()
