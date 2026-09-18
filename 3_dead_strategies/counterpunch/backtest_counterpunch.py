"""
COUNTERPUNCH — 1H mean reversion strategy designed to complement Quattro.

DESIGN PRINCIPLES:
  - Operates on 1H timeframe (more frequent than Quattro's 4H)
  - Long-only (no shorting BTC — same as Quattro)
  - Mean reversion: enter on bounces off oversold, exit on overbought
  - Regime-gated: optionally only trade when Quattro's regime is OFF
    (so the two strategies hunt in different market regimes)

ENTRY (all required at 1H bar close):
  - RSI(14) closes >= 30 having been < 30 the previous bar  (bounce off oversold)
  - Bullish candle: close > open
  - Volume confirmation: volume > 20-bar average volume
  - REGIME GATE: optional — only enter when Quattro's regime would be OFF
    (price below daily 200 EMA OR daily 200 EMA is flat/declining)

EXIT (any of these triggers at 1H close):
  - RSI(14) > 65   → take profit at next open
  - close <= entry - 2*ATR(14)  → stop loss at next open  (close-based)
  - 24 bars elapsed without exit → time stop at next open
  - Intrabar: high >= entry + 1.5*(entry-stop)  → take profit at +1.5R level

RISK:
  - 1% of account per trade (smaller than Quattro because more frequent)
  - 1 unit only, no pyramiding

We test 3 variants:
  A) Counterpunch with no regime filter (trades any market)
  B) Counterpunch regime-gated (only when Quattro is OFF)
  C) Counterpunch in periods where Quattro DOES trade (to confirm B is better)
"""
import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ── DATA ──────────────────────────────────────────────────────────────────────

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

print("Fetching 1H BTC data...")
raw_1h = fetch_full('BTC/USDT', '1h', since, exchange)
df = pd.DataFrame(raw_1h, columns=['ts','open','high','low','close','volume'])
df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
df = df.set_index('dt').drop(columns='ts')

print("Fetching daily BTC data (for regime filter)...")
raw_d = fetch_full('BTC/USDT', '1d', since_d, exchange)
df_d = pd.DataFrame(raw_d, columns=['ts','open','high','low','close','volume'])
df_d['dt'] = pd.to_datetime(df_d['ts'], unit='ms', utc=True)
df_d = df_d.set_index('dt').drop(columns='ts')

print(f"  1H bars: {len(df)}   |   Daily bars: {len(df_d)}")

# ── INDICATORS ────────────────────────────────────────────────────────────────

print("Computing indicators...")

# RSI(14) using Wilder's smoothing
delta = df['close'].diff()
gain = delta.clip(lower=0)
loss = (-delta).clip(lower=0)
avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
rs = avg_gain / avg_loss.replace(0, np.nan)
df['rsi14'] = 100 - 100 / (1 + rs)

# ATR(14) - Wilder
prev_close = df['close'].shift(1)
tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - prev_close).abs(),
    (df['low']  - prev_close).abs(),
], axis=1).max(axis=1)
df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()

# Volume 20-bar average
df['vol_avg20'] = df['volume'].rolling(20).mean()

# Daily 200 EMA + slope (Quattro's regime indicators)
df_d['ema200']     = df_d['close'].ewm(span=200, adjust=False).mean()
df_d['ema200_20d'] = df_d['ema200'].shift(20)
df_d['ema200_up']  = df_d['ema200'] > df_d['ema200_20d']
df_d_avail         = df_d[['ema200', 'ema200_up']].copy()
df_d_avail.index   = df_d_avail.index + pd.Timedelta(days=1)   # availability after close
df_d_aligned       = df_d_avail.reindex(df.index, method='ffill')
df['d_ema200']     = df_d_aligned['ema200']
df['d_ema200_up']  = df_d_aligned['ema200_up']
df['quattro_regime_on']  = (df['close'] > df['d_ema200']) & df['d_ema200_up']
df['quattro_regime_off'] = ~df['quattro_regime_on']

# Entry trigger components
df['rsi_was_oversold']   = df['rsi14'].shift(1) < 30
df['rsi_recovered']      = df['rsi14'] >= 30
df['bullish_candle']     = df['close'] > df['open']
df['volume_confirmed']   = df['volume'] > df['vol_avg20']

# ── BACKTEST ENGINE ───────────────────────────────────────────────────────────

INITIAL_BALANCE  = 1839.17
RISK_PCT         = 0.01    # 1% per trade
ATR_STOP_MULT    = 2.0
TP_R             = 1.5     # take profit at 1.5R
TIME_STOP_BARS   = 24      # exit after 24 bars (1 day) if no other exit
WARMUP           = 250

def run_backtest(regime_mode):
    """
    regime_mode:
      'none'         → ignore Quattro regime (trade always when entry conditions met)
      'quattro_off'  → only trade when Quattro regime is OFF
      'quattro_on'   → only trade when Quattro regime is ON (for comparison)
    """
    open_ = df['open'].values
    high_ = df['high'].values
    low_  = df['low'].values
    close_= df['close'].values
    rsi_  = df['rsi14'].values
    atr_  = df['atr14'].values
    was_os= df['rsi_was_oversold'].values
    recov = df['rsi_recovered'].values
    bull  = df['bullish_candle'].values
    volc  = df['volume_confirmed'].values
    regon = df['quattro_regime_on'].values
    regoff= df['quattro_regime_off'].values
    dates = df.index
    n = len(df)

    account = INITIAL_BALANCE
    trades  = []

    in_trade    = False
    entry_price = None
    stop_price  = None
    tp_price    = None
    pos_size    = None
    entry_bar   = None
    acct_at_entry = None

    for i in range(WARMUP, n - 1):

        if in_trade:
            bars_held = i - entry_bar

            # Intrabar take profit at 1.5R
            if high_[i] >= tp_price:
                exit_px = tp_price
                pnl = (exit_px - entry_price) * pos_size
                account += pnl
                trades.append({
                    'entry_date': dates[entry_bar], 'exit_date': dates[i],
                    'entry_price': entry_price, 'exit_price': exit_px,
                    'pos_size_btc': pos_size,
                    'pnl_usd': pnl, 'pnl_pct': pnl/acct_at_entry*100,
                    'R': pnl / (acct_at_entry * RISK_PCT),
                    'duration_h': bars_held,
                    'exit_reason': 'tp_15R',
                    'account': account,
                })
                in_trade = False
                continue

            # Close-based stop (next-open exit)
            if close_[i] <= stop_price:
                exit_px = open_[i+1]
                pnl = (exit_px - entry_price) * pos_size
                account += pnl
                trades.append({
                    'entry_date': dates[entry_bar], 'exit_date': dates[i+1],
                    'entry_price': entry_price, 'exit_price': exit_px,
                    'pos_size_btc': pos_size,
                    'pnl_usd': pnl, 'pnl_pct': pnl/acct_at_entry*100,
                    'R': pnl / (acct_at_entry * RISK_PCT),
                    'duration_h': bars_held + 1,
                    'exit_reason': 'stop_loss',
                    'account': account,
                })
                in_trade = False
                continue

            # RSI overbought exit
            if not np.isnan(rsi_[i]) and rsi_[i] > 65:
                exit_px = open_[i+1]
                pnl = (exit_px - entry_price) * pos_size
                account += pnl
                trades.append({
                    'entry_date': dates[entry_bar], 'exit_date': dates[i+1],
                    'entry_price': entry_price, 'exit_price': exit_px,
                    'pos_size_btc': pos_size,
                    'pnl_usd': pnl, 'pnl_pct': pnl/acct_at_entry*100,
                    'R': pnl / (acct_at_entry * RISK_PCT),
                    'duration_h': bars_held + 1,
                    'exit_reason': 'rsi_overbought',
                    'account': account,
                })
                in_trade = False
                continue

            # Time stop
            if bars_held >= TIME_STOP_BARS:
                exit_px = open_[i+1]
                pnl = (exit_px - entry_price) * pos_size
                account += pnl
                trades.append({
                    'entry_date': dates[entry_bar], 'exit_date': dates[i+1],
                    'entry_price': entry_price, 'exit_price': exit_px,
                    'pos_size_btc': pos_size,
                    'pnl_usd': pnl, 'pnl_pct': pnl/acct_at_entry*100,
                    'R': pnl / (acct_at_entry * RISK_PCT),
                    'duration_h': bars_held + 1,
                    'exit_reason': 'time_stop',
                    'account': account,
                })
                in_trade = False
                continue

        else:
            # Entry conditions
            if any(np.isnan(x) for x in [rsi_[i], atr_[i]]):
                continue
            if not (was_os[i] and recov[i] and bull[i] and volc[i]):
                continue

            # Regime filter
            if regime_mode == 'quattro_off':
                if pd.isna(regoff[i]) or not regoff[i]: continue
            elif regime_mode == 'quattro_on':
                if pd.isna(regon[i]) or not regon[i]: continue
            # else 'none' → take all signals

            entry_px = open_[i+1]
            N = atr_[i]
            stop_px = entry_px - ATR_STOP_MULT * N
            if stop_px <= 0 or entry_px - stop_px <= 0: continue

            r_amt = account * RISK_PCT
            size  = r_amt / (entry_px - stop_px)
            tp_px = entry_px + TP_R * (entry_px - stop_px)

            in_trade = True
            entry_price = entry_px
            stop_price = stop_px
            tp_price = tp_px
            pos_size = size
            entry_bar = i + 1
            acct_at_entry = account

    return pd.DataFrame(trades), account

# ── RUN VARIANTS ──────────────────────────────────────────────────────────────

print("\n=== Running variants ===\n")
print("Variant A: no regime filter...")
r_a, final_a = run_backtest('none')
print(f"  {len(r_a)} trades, final ${final_a:,.2f}")

print("Variant B: only when Quattro regime is OFF...")
r_b, final_b = run_backtest('quattro_off')
print(f"  {len(r_b)} trades, final ${final_b:,.2f}")

print("Variant C: only when Quattro regime is ON (sanity check)...")
r_c, final_c = run_backtest('quattro_on')
print(f"  {len(r_c)} trades, final ${final_c:,.2f}")

# ── METRICS ──────────────────────────────────────────────────────────────────

def metrics(r, final):
    if len(r) == 0:
        return {'trades':0,'wr':0,'aw':0,'al':0,'exp':0,'dd':0,'maxl':0,'final':final,
                'ret':(final/INITIAL_BALANCE-1)*100,'big':0,'worst':0}
    wins = r[r['R'] > 0]; losses = r[r['R'] <= 0]
    curve = [INITIAL_BALANCE] + list(r['account'])
    peak = INITIAL_BALANCE; max_dd = 0.0
    for v in curve:
        if v > peak: peak = v
        dd = (v-peak)/peak*100
        if dd < max_dd: max_dd = dd
    maxl = curl = 0
    for w in (r['R'] > 0):
        if w: curl = 0
        else: curl += 1; maxl = max(maxl, curl)
    return {
        'trades': len(r),
        'wr':   len(wins)/len(r)*100,
        'aw':   wins['R'].mean() if len(wins) else 0,
        'al':   losses['R'].mean() if len(losses) else 0,
        'exp':  r['R'].mean(),
        'dd':   max_dd, 'maxl': maxl, 'final': final,
        'ret':  (final/INITIAL_BALANCE-1)*100,
        'big':  r['R'].max(), 'worst': r['R'].min(),
    }

stats_a = metrics(r_a, final_a)
stats_b = metrics(r_b, final_b)
stats_c = metrics(r_c, final_c)

# Quattro reference (from previous backtest)
quattro = {'trades':80,'wr':27.5,'aw':14.69,'al':-2.04,'exp':2.561,'dd':-40.81,
           'maxl':6,'final':26534.52,'ret':1342.7,'big':76.67,'worst':-2.50}

sep = "─" * 100
print(f"\n{'═'*100}")
print(f"  COUNTERPUNCH BACKTEST — BTC 1H — Jan 2022 → May 2026  (start ${INITIAL_BALANCE})")
print(f"{'═'*100}")
print(f"  {'Metric':<26}{'Quattro (ref)':>16}{'CP (no regime)':>18}{'CP (Quat OFF)':>18}{'CP (Quat ON)':>18}")
print(sep)

rows = [
    ('Total trades',   'trades', '{:>18}'),
    ('Win rate %',     'wr',     '{:>18.1f}'),
    ('Avg win (R)',    'aw',     '{:>+18.2f}'),
    ('Avg loss (R)',   'al',     '{:>+18.2f}'),
    ('Expectancy (R)', 'exp',    '{:>+18.3f}'),
    ('Max drawdown %', 'dd',     '{:>+18.2f}'),
    ('Max losing streak','maxl', '{:>18}'),
    ('Final balance ($)','final','{:>18,.2f}'),
    ('Total return %', 'ret',    '{:>+18.1f}'),
    ('Biggest winner (R)','big', '{:>+18.2f}'),
    ('Worst loser (R)','worst',  '{:>+18.2f}'),
]
for lbl, key, fmt in rows:
    q_str = '{:>16}'.format(quattro.get(key, '-')) if key not in ('aw','al','exp','dd','ret','big','worst') else '{:>+16.2f}'.format(quattro[key]) if key not in ('exp',) else '{:>+16.3f}'.format(quattro[key])
    if key == 'trades' or key == 'maxl':
        q_str = '{:>16}'.format(quattro[key])
    elif key == 'final':
        q_str = '{:>16,.2f}'.format(quattro[key])
    elif key == 'wr':
        q_str = '{:>16.1f}'.format(quattro[key])
    else:
        q_str = '{:>+16.2f}'.format(quattro[key]) if key != 'exp' else '{:>+16.3f}'.format(quattro[key])
    print(f"  {lbl:<26}{q_str}{fmt.format(stats_a[key])}{fmt.format(stats_b[key])}{fmt.format(stats_c[key])}")

# Year by year for the best variant
print(f"\n{sep}")
print(f"  YEAR-BY-YEAR PnL ($)")
print(sep)
print(f"  {'Year':<8}{'CP no-regime':>20}{'CP Quattro-OFF':>20}{'CP Quattro-ON':>20}")
years = sorted(set(r_a['exit_date'].dt.year.unique()) | set(r_b['exit_date'].dt.year.unique()) | set(r_c['exit_date'].dt.year.unique()))
for yr in years:
    pa = r_a[r_a['exit_date'].dt.year == yr]['pnl_usd'].sum() if len(r_a) else 0
    pb = r_b[r_b['exit_date'].dt.year == yr]['pnl_usd'].sum() if len(r_b) else 0
    pc = r_c[r_c['exit_date'].dt.year == yr]['pnl_usd'].sum() if len(r_c) else 0
    print(f"  {yr:<8}{pa:>+20,.2f}{pb:>+20,.2f}{pc:>+20,.2f}")

# Exit reason breakdown for variant B
if len(r_b) > 0:
    print(f"\n{sep}")
    print(f"  CP Quattro-OFF — EXIT REASONS")
    print(sep)
    for reason, cnt in r_b['exit_reason'].value_counts().items():
        grp = r_b[r_b['exit_reason'] == reason]
        wr = len(grp[grp['R'] > 0]) / len(grp) * 100
        avg = grp['R'].mean()
        print(f"    {reason:<20} {cnt:>4} trades  {wr:>5.1f}% win  avg R: {avg:+.3f}")

# ── EQUITY CHART ─────────────────────────────────────────────────────────────

def curve(r):
    if len(r) == 0:
        return pd.DataFrame({'date':[df.index[WARMUP]], 'balance':[INITIAL_BALANCE]})
    return pd.DataFrame({
        'date': [r['entry_date'].iloc[0] - pd.Timedelta(hours=1)] + r['exit_date'].tolist(),
        'balance': [INITIAL_BALANCE] + r['account'].tolist(),
    })

ca = curve(r_a); cb = curve(r_b); cc = curve(r_c)

fig, ax = plt.subplots(figsize=(15, 8))
ax.plot(ca['date'], ca['balance'], label=f'CP no-regime  ({stats_a["ret"]:+.0f}%, DD {stats_a["dd"]:.0f}%)', linewidth=1.2)
ax.plot(cb['date'], cb['balance'], label=f'CP Quattro-OFF  ({stats_b["ret"]:+.0f}%, DD {stats_b["dd"]:.0f}%)', linewidth=1.5, color='#2ca02c')
ax.plot(cc['date'], cc['balance'], label=f'CP Quattro-ON  ({stats_c["ret"]:+.0f}%, DD {stats_c["dd"]:.0f}%)', linewidth=1.2, alpha=0.6)
ax.axhline(INITIAL_BALANCE, color='gray', linestyle='--', alpha=0.5)
ax.set_yscale('log')
ax.set_ylabel('Account ($, log scale)')
ax.set_title('Counterpunch — 1H Mean Reversion Backtest', fontweight='bold')
ax.legend(loc='upper left')
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
plt.tight_layout()
plt.savefig('counterpunch_equity.png', dpi=120, bbox_inches='tight')
print(f"\nChart saved -> counterpunch_equity.png")

for name, r in [('A_noregime', r_a), ('B_quattro_off', r_b), ('C_quattro_on', r_c)]:
    if len(r) > 0:
        r.to_csv(f'backtest_counterpunch_{name}.csv', index=False)
