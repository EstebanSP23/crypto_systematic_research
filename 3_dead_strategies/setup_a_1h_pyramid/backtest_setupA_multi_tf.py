"""
SETUP A — Multi-timeframe comparison: 1D vs 4H vs 1H
Goal: validate which assets have real technical edge regardless of timeframe.
Includes realistic fees (0.10% per leg, taker fees on BloFin).
"""
import ccxt
import pandas as pd
import numpy as np
import time

ASSETS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT',
    'AVAX/USDT', 'LINK/USDT', 'DOT/USDT', 'NEAR/USDT', 'MATIC/USDT', 'ATOM/USDT',
    'ARB/USDT', 'OP/USDT', 'APT/USDT', 'SUI/USDT',
    'LTC/USDT', 'ADA/USDT', 'TIA/USDT', 'SEI/USDT', 'FET/USDT',
]

INITIAL_CAPITAL = 1839.17
RISK_PCT        = 0.02
MAX_POSITIONS   = 3
SCORE_THRESHOLD = 7
FEE_PER_LEG     = 0.0010    # 0.10% taker fees on each entry/scale-out/exit

exchange = ccxt.binance()
since = exchange.parse8601('2023-01-01T00:00:00Z')

def fetch_full(symbol, timeframe, since_ms, exchange):
    all_candles = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
        if not batch: break
        all_candles.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(batch) < 1000: break
    return all_candles

def fetch_universe(timeframe):
    print(f"  Fetching {timeframe} for {len(ASSETS)} assets...")
    data = {}
    for asset in ASSETS:
        try:
            raw = fetch_full(asset, timeframe, since, exchange)
            if not raw or len(raw) < 220:
                continue
            df = pd.DataFrame(raw, columns=['ts','open','high','low','close','volume'])
            df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
            df = df.set_index('dt').drop(columns='ts').sort_index()
            df = df[~df.index.duplicated(keep='last')]
            data[asset] = df
        except Exception as e:
            print(f"    {asset}: failed — {e}")
    return data

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

def run_backtest(data):
    all_dates = sorted(set().union(*[df.index for df in data.values()]))
    account = INITIAL_CAPITAL
    positions = {}
    trades = []

    for date in all_dates:
        for sym in list(positions.keys()):
            if date not in data[sym].index: continue
            df = data[sym]
            idx = df.index.get_loc(date)
            high, low = df['high'].iloc[idx], df['low'].iloc[idx]
            pos = positions[sym]

            if low <= pos['stop_price']:
                exit_px = pos['stop_price']
                size    = pos['size'] * pos['size_remaining']
                exit_pnl = (exit_px - pos['entry_price']) * size
                # subtract exit fee
                exit_fee = exit_px * size * FEE_PER_LEG
                exit_pnl -= exit_fee
                total_pnl = exit_pnl + pos.get('partial_pnl_net', 0)
                account += exit_pnl
                trades.append({
                    'symbol': sym, 'entry_date': pos['entry_date'], 'exit_date': date,
                    'entry_price': pos['entry_price'], 'exit_price': exit_px,
                    'pnl_usd': total_pnl, 'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
                    'exit_reason': 'trailing_stop' if pos.get('scaled_out') else 'stop_loss',
                    'score': pos['score'], 'account': account,
                })
                del positions[sym]
                continue

            if not pos.get('scaled_out') and high >= pos['first_target']:
                partial_size = pos['size'] * 0.5
                partial_pnl  = (pos['first_target'] - pos['entry_price']) * partial_size
                partial_fee  = pos['first_target'] * partial_size * FEE_PER_LEG
                partial_pnl_net = partial_pnl - partial_fee
                account     += partial_pnl_net
                pos['partial_pnl_net'] = partial_pnl_net
                pos['size_remaining'] = 0.5
                pos['stop_price'] = pos['entry_price']
                pos['scaled_out'] = True

            if pos.get('scaled_out'):
                low_n = df['low'].iloc[max(0, idx-8):idx].min()
                ema20 = df['ema20'].iloc[idx]
                trailing = max(low_n, ema20) if not pd.isna(ema20) else low_n
                if trailing > pos['stop_price']:
                    pos['stop_price'] = trailing

        if len(positions) < MAX_POSITIONS:
            candidates = []
            for sym, df in data.items():
                if sym in positions or date not in df.index: continue
                idx = df.index.get_loc(date)
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
                stop_2atr = entry_price - 2 * atr
                stop_price = max(stop_2atr, consol_low) if not pd.isna(consol_low) else stop_2atr
                if stop_price >= entry_price or pd.isna(stop_price): continue
                stop_distance = entry_price - stop_price
                size = (account * RISK_PCT) / stop_distance
                # pay entry fee immediately
                entry_fee = entry_price * size * FEE_PER_LEG
                account -= entry_fee
                first_target = entry_price + 2 * stop_distance
                positions[sym] = {
                    'entry_date': df.index[idx+1], 'entry_price': entry_price,
                    'stop_price': stop_price, 'first_target': first_target,
                    'size': size, 'size_remaining': 1.0, 'acct_at_entry': account + entry_fee,
                    'score': sc, 'partial_pnl_net': -entry_fee,
                }

    for sym, pos in positions.items():
        df = data[sym]
        last_close = df['close'].iloc[-1]
        size = pos['size'] * pos['size_remaining']
        exit_pnl = (last_close - pos['entry_price']) * size
        exit_fee = last_close * size * FEE_PER_LEG
        exit_pnl -= exit_fee
        total_pnl = exit_pnl + pos.get('partial_pnl_net', 0)
        account += exit_pnl
        trades.append({
            'symbol': sym, 'entry_date': pos['entry_date'], 'exit_date': data[sym].index[-1],
            'entry_price': pos['entry_price'], 'exit_price': last_close,
            'pnl_usd': total_pnl, 'R': total_pnl / (pos['acct_at_entry'] * RISK_PCT),
            'exit_reason': 'open_at_end',
            'score': pos['score'], 'account': account,
        })
    return trades, account

# ── RUN FOR EACH TIMEFRAME ────────────────────────────────────────────────────

results = {}
for tf in ['1d', '4h', '1h']:
    print(f"\n=== TIMEFRAME: {tf} ===")
    t0 = time.time()
    data = fetch_universe(tf)
    print(f"  Loaded {len(data)} assets ({time.time()-t0:.0f}s)")

    print("  Computing indicators...")
    for asset in list(data.keys()):
        data[asset] = compute_indicators(data[asset])

    print("  Running backtest...")
    t0 = time.time()
    trades, final = run_backtest(data)
    print(f"  Done in {time.time()-t0:.0f}s. {len(trades)} trades. Final: ${final:,.2f}")
    df_t = pd.DataFrame(trades)
    if len(df_t) > 0:
        df_t['win'] = df_t['R'] > 0
        df_t['entry_date'] = pd.to_datetime(df_t['entry_date'])
        df_t['exit_date']  = pd.to_datetime(df_t['exit_date'])
    results[tf] = {'trades': df_t, 'final': final, 'data': data}

# ── COMPARISON TABLE ──────────────────────────────────────────────────────────

sep = "─" * 92
print(f"\n{'═'*92}")
print(f"  SETUP A — MULTI-TIMEFRAME COMPARISON  (threshold ≥ {SCORE_THRESHOLD}, fees 0.10%/leg)")
print(f"{'═'*92}")
print(f"  {'Timeframe':<12}{'Trades':>8}{'Win%':>8}{'Avg win R':>12}{'Avg loss R':>12}{'Exp R':>10}{'Final $':>12}{'Return %':>12}")
print(sep)
for tf in ['1d', '4h', '1h']:
    r = results[tf]['trades']
    final = results[tf]['final']
    if len(r) == 0:
        print(f"  {tf:<12} no trades")
        continue
    wins, losses = r[r['win']], r[~r['win']]
    aw = wins['R'].mean() if len(wins) else 0
    al = losses['R'].mean() if len(losses) else 0
    wr = len(wins)/len(r)*100
    exp = r['R'].mean()
    rt = (final/INITIAL_CAPITAL-1)*100
    print(f"  {tf:<12}{len(r):>8}{wr:>7.1f}%{aw:>+12.2f}{al:>+12.2f}{exp:>+10.3f}{final:>12,.2f}{rt:>+12.1f}")

# ── PER-ASSET COMPARISON (cross-timeframe edge consistency) ──────────────────

print(f"\n{sep}\n  PER-ASSET — cross-timeframe edge consistency (Exp R per trade)")
print(sep)
print(f"  {'Asset':<12}{'1D':>10}{'4H':>10}{'1H':>10}{'1D #':>8}{'4H #':>8}{'1H #':>8}")
all_syms = sorted(set().union(*[set(results[tf]['trades']['symbol'].unique()) if len(results[tf]['trades'])>0 else set() for tf in ['1d','4h','1h']]))
for sym in all_syms:
    line = f"  {sym:<12}"
    counts = ""
    for tf in ['1d', '4h', '1h']:
        r = results[tf]['trades']
        grp = r[r['symbol'] == sym] if len(r) > 0 else pd.DataFrame()
        if len(grp) == 0:
            line += f"{'-':>10}"
        else:
            line += f"{grp['R'].mean():>+10.2f}"
    for tf in ['1d', '4h', '1h']:
        r = results[tf]['trades']
        grp = r[r['symbol'] == sym] if len(r) > 0 else pd.DataFrame()
        counts += f"{len(grp):>8}"
    print(line + counts)

# Save
for tf in ['1d', '4h', '1h']:
    if len(results[tf]['trades']) > 0:
        results[tf]['trades'].to_csv(f'setupA_trades_{tf}.csv', index=False)

print(f"\nTrade logs saved -> setupA_trades_1d.csv / _4h.csv / _1h.csv")
