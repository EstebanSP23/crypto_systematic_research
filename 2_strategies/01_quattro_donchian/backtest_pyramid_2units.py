"""
Donchian Pyramid LITE — same as full pyramid but capped at MAX_UNITS = 2
"""
import ccxt
import pandas as pd
import numpy as np

def fetch_full(symbol, timeframe, since_ms, exchange):
    all_candles = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
        if not batch: break
        all_candles.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(batch) < 1000: break
    return all_candles

exchange = ccxt.binance()
since    = exchange.parse8601('2022-01-01T00:00:00Z')
since_d  = exchange.parse8601('2021-01-01T00:00:00Z')

print("Fetching data...")
raw_4h = fetch_full('BTC/USDT', '4h', since, exchange)
df = pd.DataFrame(raw_4h, columns=['ts','open','high','low','close','volume'])
df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
df = df.set_index('dt').drop(columns='ts')

raw_d = fetch_full('BTC/USDT', '1d', since_d, exchange)
df_d = pd.DataFrame(raw_d, columns=['ts','open','high','low','close','volume'])
df_d['dt'] = pd.to_datetime(df_d['ts'], unit='ms', utc=True)
df_d = df_d.set_index('dt').drop(columns='ts')

# Indicators
df['donch_high_20'] = df['high'].rolling(20).max().shift(1)
df['donch_low_10']  = df['low'].rolling(10).min().shift(1)
tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - df['close'].shift(1)).abs(),
    (df['low']  - df['close'].shift(1)).abs(),
], axis=1).max(axis=1)
df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()
df_d['ema200']    = df_d['close'].ewm(span=200, adjust=False).mean()
df_d_avail        = df_d[['ema200']].copy()
df_d_avail.index  = df_d_avail.index + pd.Timedelta(days=1)
df_d_aligned      = df_d_avail.reindex(df.index, method='ffill')
df['d_ema200']    = df_d_aligned['ema200']
df['regime_up']   = df['close'] > df['d_ema200']

INITIAL_BALANCE = 1839.17
RISK_PCT        = 0.02
HARD_STOP_PCT   = 0.05
PYRAMID_STEP    = 0.5
MAX_UNITS       = 2          # ← THE CHANGE
MAX_LEVERAGE    = 20
WARMUP          = 250

open_  = df['open'].values
high_  = df['high'].values
low_   = df['low'].values
close_ = df['close'].values
dhigh_ = df['donch_high_20'].values
dlow_  = df['donch_low_10'].values
atr_   = df['atr14'].values
reg_   = df['regime_up'].values
dates_ = df.index
n      = len(df)

account = INITIAL_BALANCE
trades  = []
in_trade = False
units = []
original_entry = original_atr = common_stop = hard_stop = acct_at_entry = None
pending_exit = False
pending_exit_reason = None

def total_size(): return sum(u['size'] for u in units)
def total_notional(p): return sum(u['size']*p for u in units)
def total_pnl_at(p): return sum((p - u['entry_price'])*u['size'] for u in units)

def close_all_units(exit_px, reason, i):
    global account, in_trade, units, original_entry, original_atr, common_stop, hard_stop, acct_at_entry
    total_pnl = total_pnl_at(exit_px)
    avg_entry = sum(u['entry_price']*u['size'] for u in units) / total_size()
    account += total_pnl
    trades.append({
        'entry_date': dates_[units[0]['entry_bar']], 'exit_date': dates_[i],
        'first_entry_price': units[0]['entry_price'], 'avg_entry_price': avg_entry,
        'exit_price': exit_px, 'num_units': len(units),
        'total_size_btc': total_size(), 'original_atr': original_atr,
        'first_unit_risk': acct_at_entry * RISK_PCT,
        'pnl_usd': total_pnl, 'pnl_pct': total_pnl/acct_at_entry*100,
        'R_total': total_pnl / (acct_at_entry * RISK_PCT),
        'duration_h': (i - units[0]['entry_bar'])*4,
        'exit_reason': reason, 'account': account,
    })
    in_trade = False
    units = []
    original_entry = original_atr = common_stop = hard_stop = acct_at_entry = None

for i in range(WARMUP, n - 1):
    if pending_exit:
        close_all_units(open_[i], pending_exit_reason, i)
        pending_exit = False
        pending_exit_reason = None

    if in_trade:
        # Hard 5% stop
        if total_pnl_at(low_[i]) <= -HARD_STOP_PCT * acct_at_entry:
            target_loss = -HARD_STOP_PCT * acct_at_entry
            wavg_entry  = sum(u['entry_price']*u['size'] for u in units) / total_size()
            exit_px     = wavg_entry + target_loss / total_size()
            close_all_units(exit_px, 'hard_stop_5pct', i)
            continue

        # 2*ATR trailing stop (wick-based)
        if low_[i] <= common_stop:
            close_all_units(common_stop, 'atr_stop_trailing', i)
            continue

        # Pyramiding
        while len(units) < MAX_UNITS:
            next_trigger = original_entry + PYRAMID_STEP * len(units) * original_atr
            if high_[i] < next_trigger: break
            unit_entry = next_trigger
            r_amt = acct_at_entry * RISK_PCT
            size  = r_amt / (2 * original_atr)
            lev   = (total_notional(close_[i]) + size*unit_entry) / account
            if lev > MAX_LEVERAGE: break
            units.append({'entry_price': unit_entry, 'size': size, 'entry_bar': i})
            new_stop = unit_entry - 2*original_atr
            if new_stop > common_stop: common_stop = new_stop
            target_loss = -HARD_STOP_PCT * acct_at_entry
            wavg_entry  = sum(u['entry_price']*u['size'] for u in units) / total_size()
            hard_stop   = wavg_entry + target_loss / total_size()

        # Donchian exit
        if close_[i] < dlow_[i]:
            pending_exit = True
            pending_exit_reason = 'donchian_exit'
            continue

    else:
        if np.isnan(dhigh_[i]) or np.isnan(atr_[i]) or np.isnan(reg_[i]): continue
        if close_[i] > dhigh_[i] and reg_[i]:
            entry_px = open_[i+1]
            N = atr_[i]
            stop_px = entry_px - 2*N
            if entry_px - stop_px <= 0: continue
            r_amt = account * RISK_PCT
            size  = r_amt / (2*N)
            lev   = (size * entry_px) / account
            if lev > MAX_LEVERAGE: continue
            in_trade = True
            original_entry = entry_px
            original_atr = N
            acct_at_entry = account
            common_stop = stop_px
            units = [{'entry_price': entry_px, 'size': size, 'entry_bar': i+1}]
            hard_stop = entry_px - (HARD_STOP_PCT * account / size)

if in_trade:
    close_all_units(close_[n-1], 'still_open_at_end', n-1)

r = pd.DataFrame(trades)
r.to_csv('backtest_pyramid_2units_results.csv', index=False)
print(f"Saved {len(r)} trades  ->  backtest_pyramid_2units_results.csv")
print(f"Final balance: ${account:,.2f}   Return: {(account/INITIAL_BALANCE-1)*100:+.1f}%")
