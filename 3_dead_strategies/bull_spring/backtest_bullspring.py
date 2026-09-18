"""
BULL SPRING — BTC 4H long compression-breakout strategy.

ENTRY (all required at 4H bar close):
  - EMA 21 > EMA 55                      (uptrend regime)
  - BBWP < 35                            (compression)
  - BBWP MA (SMA 5) sloping DOWN         (volatility still contracting)
  - Stochastic %D sloping UP             (momentum turning up)

EXIT:
  - BBWP > 80 on candle close → exit next bar open (take profit)
  - Price drops 5% from entry → stop loss (intrabar via low)

RISK: 5% price stop. Tests TWO sizing variants:
  V1) 2% account risk → position = 40% of account at 1× leverage
  V2) 5% account risk → position = 100% of account at 1× leverage (max aggression)
"""
import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

exchange = ccxt.binance()
since = exchange.parse8601('2022-01-01T00:00:00Z')

def fetch_full(symbol, timeframe, since_ms, exchange):
    all_candles = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
        if not batch: break
        all_candles.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(batch) < 1000: break
    return all_candles

print("Fetching BTC 4H data...")
raw = fetch_full('BTC/USDT', '4h', since, exchange)
df = pd.DataFrame(raw, columns=['ts','open','high','low','close','volume'])
df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
df = df.set_index('dt').drop(columns='ts').sort_index()
df = df[~df.index.duplicated(keep='last')]
print(f"  {len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}")

print("Computing indicators...")
df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
df['ema55'] = df['close'].ewm(span=55, adjust=False).mean()

basis = df['close'].rolling(13).mean()
df['bbw'] = 2 * df['close'].rolling(13).std(ddof=0) / basis
bbw = df['bbw'].values
bbwp = np.full(len(df), np.nan)
for i in range(13, len(df)):
    start = max(13, i - 252)
    h = bbw[start:i]
    valid = h[~np.isnan(h)]
    if len(valid) > 0:
        bbwp[i] = np.sum(valid <= bbw[i]) / len(valid) * 100
df['bbwp']    = bbwp
df['bbwp_ma'] = df['bbwp'].rolling(5).mean()

n_high = df['high'].rolling(14).max()
n_low  = df['low'].rolling(14).min()
df['stoch_k_raw'] = ((df['close'] - n_low) / (n_high - n_low).replace(0, np.nan)) * 100
df['stoch_k']     = df['stoch_k_raw'].rolling(6).mean()
df['stoch_d']     = df['stoch_k'].rolling(3).mean()

INITIAL_BALANCE = 1839.17
STOP_PCT        = 0.05     # 5% price-based stop
FEE_PER_LEG     = 0.0010   # 0.10% taker fees
WARMUP          = 400

def run_backtest(risk_pct):
    """
    risk_pct: max % account loss per trade (used to size position relative to 5% stop)
    position_notional = (account * risk_pct) / STOP_PCT
    """
    open_, high_, low_, close_ = df['open'].values, df['high'].values, df['low'].values, df['close'].values
    ema21_, ema55_ = df['ema21'].values, df['ema55'].values
    bbwp_, bbwpma_ = df['bbwp'].values, df['bbwp_ma'].values
    stochd_ = df['stoch_d'].values
    dates = df.index

    account = INITIAL_BALANCE
    trades = []
    in_trade = False
    entry_price = stop_price = pos_size = entry_bar = acct_at_entry = None

    for i in range(WARMUP, len(df) - 1):
        if in_trade:
            # Stop loss (intrabar via low)
            if low_[i] <= stop_price:
                exit_px = stop_price
                pnl = (exit_px - entry_price) * pos_size
                exit_fee = exit_px * pos_size * FEE_PER_LEG
                pnl -= exit_fee
                account += pnl
                trades.append({
                    'entry_date': dates[entry_bar], 'exit_date': dates[i],
                    'entry_price': entry_price, 'exit_price': exit_px,
                    'pos_size_btc': pos_size, 'pnl_usd': pnl,
                    'pnl_pct': pnl / acct_at_entry * 100,
                    'duration_h': (i - entry_bar) * 4,
                    'exit_reason': 'stop_loss_5pct',
                    'account': account,
                })
                in_trade = False
                continue

            # Take profit on BBWP > 80 close → exit next bar open
            if not np.isnan(bbwp_[i]) and bbwp_[i] > 80:
                exit_px = open_[i+1]
                pnl = (exit_px - entry_price) * pos_size
                exit_fee = exit_px * pos_size * FEE_PER_LEG
                pnl -= exit_fee
                account += pnl
                trades.append({
                    'entry_date': dates[entry_bar], 'exit_date': dates[i+1],
                    'entry_price': entry_price, 'exit_price': exit_px,
                    'pos_size_btc': pos_size, 'pnl_usd': pnl,
                    'pnl_pct': pnl / acct_at_entry * 100,
                    'duration_h': (i + 1 - entry_bar) * 4,
                    'exit_reason': 'bbwp_above_80',
                    'account': account,
                })
                in_trade = False
                continue

        else:
            if any(np.isnan(x) for x in [ema21_[i], ema55_[i], bbwp_[i], bbwpma_[i], bbwpma_[i-1], stochd_[i], stochd_[i-1]]):
                continue

            cond_ema    = ema21_[i] > ema55_[i]
            cond_bbwp   = bbwp_[i] < 35
            cond_bbwpma = bbwpma_[i] < bbwpma_[i-1]
            cond_stoch  = stochd_[i] > stochd_[i-1]

            if not (cond_ema and cond_bbwp and cond_bbwpma and cond_stoch):
                continue

            entry_px = open_[i+1]
            stop_px  = entry_px * (1 - STOP_PCT)
            notional = (account * risk_pct) / STOP_PCT
            size     = notional / entry_px
            entry_fee = entry_px * size * FEE_PER_LEG
            account -= entry_fee

            in_trade = True
            entry_price = entry_px
            stop_price = stop_px
            pos_size = size
            entry_bar = i + 1
            acct_at_entry = account + entry_fee

    # Close any open trade at end
    if in_trade:
        exit_px = close_[-1]
        pnl = (exit_px - entry_price) * pos_size - exit_px * pos_size * FEE_PER_LEG
        account += pnl
        trades.append({
            'entry_date': dates[entry_bar], 'exit_date': dates[-1],
            'entry_price': entry_price, 'exit_price': exit_px,
            'pos_size_btc': pos_size, 'pnl_usd': pnl,
            'pnl_pct': pnl / acct_at_entry * 100,
            'duration_h': (len(df) - 1 - entry_bar) * 4,
            'exit_reason': 'still_open',
            'account': account,
        })
    return pd.DataFrame(trades), account

# Run both variants
print("\nRunning variant 1: 2% account risk per trade...")
r1, final_1 = run_backtest(0.02)
print(f"  {len(r1)} trades, final ${final_1:,.2f}")

print("Running variant 2: 5% account risk per trade...")
r2, final_2 = run_backtest(0.05)
print(f"  {len(r2)} trades, final ${final_2:,.2f}")

def stats(r, final):
    if len(r) == 0:
        return None
    r['win'] = r['pnl_usd'] > 0
    r['entry_date'] = pd.to_datetime(r['entry_date'])
    r['exit_date']  = pd.to_datetime(r['exit_date'])
    r['year']       = r['exit_date'].dt.year
    wins, losses = r[r['win']], r[~r['win']]
    # Drawdown from equity curve
    curve = [INITIAL_BALANCE] + list(r['account'])
    peak = INITIAL_BALANCE; mdd = 0
    for v in curve:
        if v > peak: peak = v
        d = (v-peak)/peak*100
        if d < mdd: mdd = d
    max_w = max_l = cur_w = cur_l = 0
    for w in r['win']:
        if w: cur_w += 1; cur_l = 0; max_w = max(max_w, cur_w)
        else: cur_l += 1; cur_w = 0; max_l = max(max_l, cur_l)
    days = (r['exit_date'].iloc[-1] - r['entry_date'].iloc[0]).days
    apy = ((final/INITIAL_BALANCE) ** (365/max(days,1)) - 1) * 100
    return {
        'trades': len(r), 'win_rate': len(wins)/len(r)*100,
        'avg_win': wins['pnl_pct'].mean() if len(wins) else 0,
        'avg_loss': losses['pnl_pct'].mean() if len(losses) else 0,
        'best': r['pnl_pct'].max(), 'worst': r['pnl_pct'].min(),
        'max_w': max_w, 'max_l': max_l, 'mdd': mdd, 'apy': apy,
        'final': final, 'ret': (final/INITIAL_BALANCE-1)*100, 'r': r,
    }

s1 = stats(r1, final_1)
s2 = stats(r2, final_2)

sep = "─" * 90
print(f"\n{'═'*90}")
print(f"  BULL SPRING — BTC 4H — Jan 2022 → {df.index[-1].date()}  (start ${INITIAL_BALANCE})")
print(f"  Stop: 5% below entry  |  Exit: BBWP > 80 close  |  Fees: 0.10%/leg")
print(f"{'═'*90}")
print(f"  {'Metric':<28}{'V1: 2% risk':>22}{'V2: 5% risk':>22}")
print(sep)
print(f"  {'Total trades':<28}{s1['trades']:>22}{s2['trades']:>22}")
print(f"  {'Win rate %':<28}{s1['win_rate']:>22.1f}{s2['win_rate']:>22.1f}")
print(f"  {'Avg win %':<28}{s1['avg_win']:>+22.2f}{s2['avg_win']:>+22.2f}")
print(f"  {'Avg loss %':<28}{s1['avg_loss']:>+22.2f}{s2['avg_loss']:>+22.2f}")
print(f"  {'Best trade %':<28}{s1['best']:>+22.2f}{s2['best']:>+22.2f}")
print(f"  {'Worst trade %':<28}{s1['worst']:>+22.2f}{s2['worst']:>+22.2f}")
print(f"  {'Max winning streak':<28}{s1['max_w']:>22}{s2['max_w']:>22}")
print(f"  {'Max losing streak':<28}{s1['max_l']:>22}{s2['max_l']:>22}")
print(f"  {'Max drawdown %':<28}{s1['mdd']:>+22.2f}{s2['mdd']:>+22.2f}")
print(f"  {'Final balance ($)':<28}{s1['final']:>22,.2f}{s2['final']:>22,.2f}")
print(f"  {'Total return %':<28}{s1['ret']:>+22.1f}{s2['ret']:>+22.1f}")
print(f"  {'APY %':<28}{s1['apy']:>+22.1f}{s2['apy']:>+22.1f}")

for label, s in [('V1 (2% risk)', s1), ('V2 (5% risk)', s2)]:
    print(f"\n{sep}\n  {label} — YEAR-BY-YEAR")
    print(sep)
    print(f"  {'Year':<8}{'Trades':>8}{'Win%':>8}{'PnL $':>14}")
    for yr, grp in s['r'].groupby('year'):
        wr = len(grp[grp['win']])/len(grp)*100
        print(f"  {yr:<8}{len(grp):>8}{wr:>7.1f}%{grp['pnl_usd'].sum():>+14,.2f}")
    print(f"\n  Exit reasons:")
    for reason, cnt in s['r']['exit_reason'].value_counts().items():
        grp = s['r'][s['r']['exit_reason'] == reason]
        wr = len(grp[grp['win']])/len(grp)*100
        avg = grp['pnl_pct'].mean()
        print(f"    {reason:<20} {cnt:>4} trades  {wr:>5.1f}% win  avg pct: {avg:+.2f}%")

# Chart
def curve(r):
    if len(r) == 0:
        return pd.DataFrame({'date':[df.index[WARMUP]], 'balance':[INITIAL_BALANCE]})
    return pd.DataFrame({
        'date': [r['entry_date'].iloc[0] - pd.Timedelta(hours=4)] + r['exit_date'].tolist(),
        'balance': [INITIAL_BALANCE] + r['account'].tolist(),
    })

c1, c2 = curve(r1), curve(r2)
fig, ax = plt.subplots(figsize=(15, 7))
ax.plot(c1['date'], c1['balance'], color='#1f77b4', linewidth=1.4,
        label=f"V1: 2% risk  ({s1['ret']:+.0f}%, {s1['apy']:+.1f}% APY, DD {s1['mdd']:.0f}%)")
ax.plot(c2['date'], c2['balance'], color='#d62728', linewidth=1.4,
        label=f"V2: 5% risk  ({s2['ret']:+.0f}%, {s2['apy']:+.1f}% APY, DD {s2['mdd']:.0f}%)")
ax.axhline(INITIAL_BALANCE, color='gray', linestyle='--', alpha=0.5)
# lending baseline
days_idx = (c1['date'] - c1['date'].iloc[0]).dt.days
lending = INITIAL_BALANCE * (1 + 0.06/365) ** days_idx
ax.plot(c1['date'], lending, '--', color='green', alpha=0.5, label='USDT lending 6% APY')
ax.set_ylabel('Account ($)')
ax.set_title('Bull Spring — BTC 4H Compression Breakout', fontweight='bold')
ax.legend(loc='upper left')
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
plt.tight_layout()
plt.savefig('bullspring.png', dpi=120, bbox_inches='tight')
print(f"\nChart -> bullspring.png")
