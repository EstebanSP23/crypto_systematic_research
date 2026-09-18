"""
BEAR EDGE — 1H short strategy on BTC.

INDICATORS:
  - EMA 21, 55                        (trend regime)
  - BBWP (SMA basis 13, lookback 252) + SMA(5) signal line
  - Stochastic (%K=14, %K-smooth=6, %D-smooth=3)
  - PMARP (VWMA basis 20, lookback 350)
  - LuxAlgo Pivot HIGH (15/15) for resistance

ENTRY (short, all required at 1H bar close):
  - EMA 55 > EMA 21          (downtrend regime)
  - BBWP < 35                (compression)
  - BBWP MA sloping down     (volatility contracting)
  - Stoch %D sloping down    (momentum down)
  - Optional: day filter (Thursday or Saturday only)

EXIT (whichever triggers first):
  - 2% take profit (intrabar)            → price-based
  - 2% stop loss   (intrabar)            → price-based
  - 1H close > LuxAlgo resistance        → exit next open
  - PMARP < 10                            → exit next open

RISK: 1% of account per trade.
POSITION SIZING: position notional = risk_amt / 0.02 (the 2% stop distance).
NOTE: funding rate cost is NOT modeled in this backtest. Real-world results
will be slightly worse during periods of positive funding (longs dominant).
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

print("Fetching 1H BTC data...")
raw_1h = fetch_full('BTC/USDT', '1h', since, exchange)
df = pd.DataFrame(raw_1h, columns=['ts','open','high','low','close','volume'])
df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
df = df.set_index('dt').drop(columns='ts')
print(f"  {len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}")

# ── INDICATORS ────────────────────────────────────────────────────────────────

print("Computing indicators...")

# EMA 21 and 55
df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
df['ema55'] = df['close'].ewm(span=55, adjust=False).mean()

# BBWP — SMA basis 13, lookback 252
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
df['bbwp']    = bbwp
df['bbwp_ma'] = df['bbwp'].rolling(5).mean()

# Stochastic — %K=14, %K smoothing=6, %D smoothing=3
n_high = df['high'].rolling(14).max()
n_low  = df['low'].rolling(14).min()
df['stoch_k_raw'] = ((df['close'] - n_low) / (n_high - n_low).replace(0, np.nan)) * 100
df['stoch_k']     = df['stoch_k_raw'].rolling(6).mean()
df['stoch_d']     = df['stoch_k'].rolling(3).mean()

# PMARP — VWMA basis 20, lookback 350
def vwma(price, volume, length):
    return (price * volume).rolling(length).sum() / volume.rolling(length).sum()

df['vwma20'] = vwma(df['close'], df['volume'], 20)
df['pmar']   = (df['close'] / df['vwma20']).abs()

pmar_arr = df['pmar'].values
pmarp = np.full(len(df), np.nan)
for i in range(350, len(df)):
    h = pmar_arr[i-350:i]
    valid = h[~np.isnan(h)]
    if len(valid) > 0:
        pmarp[i] = np.sum(valid <= pmar_arr[i]) / len(valid) * 100
df['pmarp'] = pmarp

# LuxAlgo Pivot HIGH (15/15)
print("  Detecting pivot highs (15/15)...")
highs = df['high'].values
n = len(df)
pivot_raw = np.full(n, np.nan)
for i in range(15, n - 15):
    hi = highs[i]
    if (hi > highs[i-15:i]).all() and (hi > highs[i+1:i+16]).all():
        pivot_raw[i + 15] = hi
df['resistance'] = pd.Series(pivot_raw, index=df.index).ffill().shift(1)

# Day-of-week (UTC) — Mon=0 ... Sat=5, Sun=6
df['dow'] = df.index.dayofweek

# ── BACKTEST ──────────────────────────────────────────────────────────────────

INITIAL_BALANCE = 1839.17
RISK_PCT  = 0.01     # 1% per trade
STOP_PCT  = 0.02     # 2% above entry for short
TP_PCT    = 0.02     # 2% below entry for short
MAX_LEVERAGE = 20
WARMUP    = 400

def run_backtest(day_filter=None):
    """
    day_filter: None      → all days
                {3, 5}    → Thursday or Saturday only (UTC)
    """
    open_ = df['open'].values
    high_ = df['high'].values
    low_  = df['low'].values
    close_= df['close'].values
    ema21_= df['ema21'].values
    ema55_= df['ema55'].values
    bbwp_ = df['bbwp'].values
    bbwpma_= df['bbwp_ma'].values
    stochd_= df['stoch_d'].values
    pmarp_= df['pmarp'].values
    resist_= df['resistance'].values
    dow_  = df['dow'].values
    dates = df.index

    account = INITIAL_BALANCE
    trades  = []

    in_trade = False
    entry_price = stop_price = tp_price = pos_size = entry_bar = acct_at_entry = None

    for i in range(WARMUP, n - 1):
        if in_trade:
            bars_held = i - entry_bar

            # Stop loss: price rose 2% (intrabar via bar high)
            if high_[i] >= stop_price:
                exit_px = stop_price
                pnl = (entry_price - exit_px) * pos_size   # SHORT: profit when exit < entry
                account += pnl
                trades.append({
                    'entry_date': dates[entry_bar], 'exit_date': dates[i],
                    'entry_price': entry_price, 'exit_price': exit_px,
                    'pos_size_btc': pos_size,
                    'pnl_usd': pnl, 'pnl_pct': pnl / acct_at_entry * 100,
                    'R': pnl / (acct_at_entry * RISK_PCT),
                    'duration_h': bars_held,
                    'exit_reason': 'stop_loss_2pct',
                    'account': account,
                })
                in_trade = False
                continue

            # Take profit: price fell 2% (intrabar via bar low)
            if low_[i] <= tp_price:
                exit_px = tp_price
                pnl = (entry_price - exit_px) * pos_size
                account += pnl
                trades.append({
                    'entry_date': dates[entry_bar], 'exit_date': dates[i],
                    'entry_price': entry_price, 'exit_price': exit_px,
                    'pos_size_btc': pos_size,
                    'pnl_usd': pnl, 'pnl_pct': pnl / acct_at_entry * 100,
                    'R': pnl / (acct_at_entry * RISK_PCT),
                    'duration_h': bars_held,
                    'exit_reason': 'take_profit_2pct',
                    'account': account,
                })
                in_trade = False
                continue

            # LuxAlgo resistance break: close > most recent confirmed pivot high
            if not np.isnan(resist_[i]) and close_[i] > resist_[i]:
                exit_px = open_[i+1]
                pnl = (entry_price - exit_px) * pos_size
                account += pnl
                trades.append({
                    'entry_date': dates[entry_bar], 'exit_date': dates[i+1],
                    'entry_price': entry_price, 'exit_price': exit_px,
                    'pos_size_btc': pos_size,
                    'pnl_usd': pnl, 'pnl_pct': pnl / acct_at_entry * 100,
                    'R': pnl / (acct_at_entry * RISK_PCT),
                    'duration_h': bars_held + 1,
                    'exit_reason': 'luxalgo_resistance',
                    'account': account,
                })
                in_trade = False
                continue

            # PMARP < 10 → max profit exit
            if not np.isnan(pmarp_[i]) and pmarp_[i] < 10:
                exit_px = open_[i+1]
                pnl = (entry_price - exit_px) * pos_size
                account += pnl
                trades.append({
                    'entry_date': dates[entry_bar], 'exit_date': dates[i+1],
                    'entry_price': entry_price, 'exit_price': exit_px,
                    'pos_size_btc': pos_size,
                    'pnl_usd': pnl, 'pnl_pct': pnl / acct_at_entry * 100,
                    'R': pnl / (acct_at_entry * RISK_PCT),
                    'duration_h': bars_held + 1,
                    'exit_reason': 'pmarp_below_10',
                    'account': account,
                })
                in_trade = False
                continue

        else:
            # Skip if NaN indicators
            if any(np.isnan(x) for x in [ema21_[i], ema55_[i], bbwp_[i], bbwpma_[i],
                                          bbwpma_[i-1], stochd_[i], stochd_[i-1]]):
                continue

            # Day filter check
            if day_filter is not None and dow_[i] not in day_filter:
                continue

            # Entry conditions
            cond_ema    = ema55_[i] > ema21_[i]               # downtrend
            cond_bbwp   = bbwp_[i] < 35                       # compression
            cond_bbwpma = bbwpma_[i] < bbwpma_[i-1]           # BBWP MA declining
            cond_stoch  = stochd_[i] < stochd_[i-1]           # %D declining

            if not (cond_ema and cond_bbwp and cond_bbwpma and cond_stoch):
                continue

            # Enter SHORT at next bar open
            entry_px = open_[i+1]
            stop_px  = entry_px * (1 + STOP_PCT)
            tp_px    = entry_px * (1 - TP_PCT)

            r_amt = account * RISK_PCT
            size  = r_amt / (entry_px * STOP_PCT)
            notional = size * entry_px
            leverage = notional / account
            if leverage > MAX_LEVERAGE:
                continue

            in_trade = True
            entry_price = entry_px
            stop_price  = stop_px
            tp_price    = tp_px
            pos_size    = size
            entry_bar   = i + 1
            acct_at_entry = account

    return pd.DataFrame(trades), account

# ── RUN VARIANTS ──────────────────────────────────────────────────────────────

print("\nRunning variant A: no day filter...")
r_a, final_a = run_backtest(day_filter=None)
print(f"  {len(r_a)} trades, final ${final_a:,.2f}")

print("Running variant B: Thursday or Saturday only...")
r_b, final_b = run_backtest(day_filter={3, 5})
print(f"  {len(r_b)} trades, final ${final_b:,.2f}")

# ── METRICS ──────────────────────────────────────────────────────────────────

def metrics(r, final):
    if len(r) == 0:
        return {'trades':0,'wr':0,'aw':0,'al':0,'exp':0,'dd':0,'maxl':0,'maxw':0,'final':final,
                'ret':(final/INITIAL_BALANCE-1)*100,'big':0,'worst':0}
    wins = r[r['R'] > 0]; losses = r[r['R'] <= 0]
    curve = [INITIAL_BALANCE] + list(r['account'])
    peak = INITIAL_BALANCE; max_dd = 0.0
    for v in curve:
        if v > peak: peak = v
        dd = (v-peak)/peak*100
        if dd < max_dd: max_dd = dd
    maxl = maxw = curl = curw = 0
    for w in (r['R'] > 0):
        if w: curw += 1; curl = 0; maxw = max(maxw, curw)
        else: curl += 1; curw = 0; maxl = max(maxl, curl)
    return {
        'trades': len(r),
        'wr': len(wins)/len(r)*100,
        'aw': wins['R'].mean() if len(wins) else 0,
        'al': losses['R'].mean() if len(losses) else 0,
        'exp': r['R'].mean(),
        'dd': max_dd, 'maxl': maxl, 'maxw': maxw, 'final': final,
        'ret': (final/INITIAL_BALANCE-1)*100,
        'big': r['R'].max(), 'worst': r['R'].min(),
    }

stats_a = metrics(r_a, final_a)
stats_b = metrics(r_b, final_b)

sep = "─" * 88
print(f"\n{'═'*88}")
print(f"  BEAR EDGE BACKTEST — BTC 1H — Jan 2022 → May 2026  (start ${INITIAL_BALANCE})")
print(f"{'═'*88}")
print(f"  {'Metric':<28}{'No day filter':>20}{'Thu/Sat only':>20}")
print(sep)
rows = [
    ('Total trades',          'trades','{:>20}'),
    ('Win rate %',            'wr',    '{:>20.1f}'),
    ('Avg win (R)',           'aw',    '{:>+20.2f}'),
    ('Avg loss (R)',          'al',    '{:>+20.2f}'),
    ('Expectancy (R)',        'exp',   '{:>+20.3f}'),
    ('Max drawdown %',        'dd',    '{:>+20.2f}'),
    ('Max losing streak',     'maxl',  '{:>20}'),
    ('Max winning streak',    'maxw',  '{:>20}'),
    ('Final balance ($)',     'final', '{:>20,.2f}'),
    ('Total return %',        'ret',   '{:>+20.1f}'),
    ('Biggest winner (R)',    'big',   '{:>+20.2f}'),
    ('Worst loser (R)',       'worst', '{:>+20.2f}'),
]
for lbl, key, fmt in rows:
    print(f"  {lbl:<28}{fmt.format(stats_a[key])}{fmt.format(stats_b[key])}")

# Year by year
print(f"\n{sep}")
print(f"  YEAR-BY-YEAR P&L (USD)")
print(sep)
print(f"  {'Year':<8}{'No filter':>20}{'Thu/Sat only':>20}")
all_years = sorted(set(r_a['exit_date'].dt.year.unique()) | set(r_b['exit_date'].dt.year.unique())) if len(r_a) or len(r_b) else []
for yr in all_years:
    pa = r_a[r_a['exit_date'].dt.year == yr]['pnl_usd'].sum() if len(r_a) else 0
    pb = r_b[r_b['exit_date'].dt.year == yr]['pnl_usd'].sum() if len(r_b) else 0
    print(f"  {yr:<8}{pa:>+20,.2f}{pb:>+20,.2f}")

# Exit reason breakdown
for label, r in [('NO FILTER', r_a), ('THU/SAT', r_b)]:
    if len(r) == 0: continue
    print(f"\n{sep}")
    print(f"  EXIT REASONS — {label}")
    print(sep)
    for reason, cnt in r['exit_reason'].value_counts().items():
        grp = r[r['exit_reason'] == reason]
        wr = len(grp[grp['R'] > 0]) / len(grp) * 100
        avg = grp['R'].mean()
        print(f"    {reason:<22} {cnt:>4} trades  {wr:>5.1f}% win  avg R: {avg:+.3f}")

# Day-of-week breakdown for the no-filter variant (to validate the Thu/Sat thesis)
if len(r_a) > 0:
    print(f"\n{sep}")
    print(f"  DAY-OF-WEEK BREAKDOWN (no-filter variant) — does Thu/Sat thesis hold?")
    print(sep)
    print(f"  {'Day':<12}{'Trades':>8}{'Win %':>10}{'Avg R':>10}{'Total $':>12}")
    r_a['entry_dow'] = pd.to_datetime(r_a['entry_date']).dt.day_name()
    dow_order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
    for d in dow_order:
        grp = r_a[r_a['entry_dow'] == d]
        if len(grp) == 0:
            print(f"  {d:<12}{'-':>8}{'-':>10}{'-':>10}{'-':>12}")
            continue
        wr = len(grp[grp['R'] > 0]) / len(grp) * 100
        avg = grp['R'].mean()
        total = grp['pnl_usd'].sum()
        print(f"  {d:<12}{len(grp):>8}{wr:>9.1f}%{avg:>+10.3f}{total:>+12,.2f}")

# ── EQUITY CHART ─────────────────────────────────────────────────────────────

def curve(r):
    if len(r) == 0:
        return pd.DataFrame({'date':[df.index[WARMUP]], 'balance':[INITIAL_BALANCE]})
    return pd.DataFrame({
        'date': [r['entry_date'].iloc[0] - pd.Timedelta(hours=1)] + r['exit_date'].tolist(),
        'balance': [INITIAL_BALANCE] + r['account'].tolist(),
    })

ca = curve(r_a); cb = curve(r_b)
fig, ax = plt.subplots(figsize=(15, 8))
ax.plot(ca['date'], ca['balance'], label=f'No filter  ({stats_a["ret"]:+.0f}%, DD {stats_a["dd"]:.0f}%, {stats_a["trades"]} trades)', linewidth=1.2)
ax.plot(cb['date'], cb['balance'], label=f'Thu/Sat only  ({stats_b["ret"]:+.0f}%, DD {stats_b["dd"]:.0f}%, {stats_b["trades"]} trades)', linewidth=1.5, color='#d62728')
ax.axhline(INITIAL_BALANCE, color='gray', linestyle='--', alpha=0.5)
ax.set_yscale('log')
ax.set_ylabel('Account ($, log scale)')
ax.set_title('Bear Edge — BTC 1H Short Strategy', fontweight='bold')
ax.legend(loc='upper left')
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
plt.tight_layout()
plt.savefig('bearedge_equity.png', dpi=120, bbox_inches='tight')
print(f"\nChart -> bearedge_equity.png")

for name, r in [('A_nofilter', r_a), ('B_thu_sat', r_b)]:
    if len(r) > 0:
        r.to_csv(f'backtest_bearedge_{name}.csv', index=False)
