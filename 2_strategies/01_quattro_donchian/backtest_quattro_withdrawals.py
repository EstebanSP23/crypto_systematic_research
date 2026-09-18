"""
Quattro + Profit-Taking Withdrawal Rule
Same locked Quattro strategy, but withdraw $460 (25% of starting capital)
every time the account passes a new $1,839 milestone above starting.
Compare against Quattro with no withdrawals (full compounding).
"""
import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

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
prev_close = df['close'].shift(1)
tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - prev_close).abs(),
    (df['low']  - prev_close).abs(),
], axis=1).max(axis=1)
df['atr14'] = tr.ewm(alpha=1/14, adjust=False).mean()

df_d['ema200']      = df_d['close'].ewm(span=200, adjust=False).mean()
df_d['ema200_20d']  = df_d['ema200'].shift(20)
df_d['ema200_up']   = df_d['ema200'] > df_d['ema200_20d']
df_d_avail          = df_d[['ema200', 'ema200_up']].copy()
df_d_avail.index    = df_d_avail.index + pd.Timedelta(days=1)
df_d_aligned        = df_d_avail.reindex(df.index, method='ffill')
df['d_ema200']      = df_d_aligned['ema200']
df['d_ema200_up']   = df_d_aligned['ema200_up']
df['regime_up']     = df['close'] > df['d_ema200']

INITIAL_BALANCE = 1839.17
RISK_PCT        = 0.02
HARD_STOP_PCT   = 0.05
PYRAMID_STEP    = 0.5
MAX_UNITS       = 4
MAX_LEVERAGE    = 20
WARMUP          = 250

# Withdrawal rule: every $1,839 milestone, withdraw $460 (= 25% of starting capital)
WITHDRAW_INCREMENT = INITIAL_BALANCE          # next milestone = current_milestone + $1,839
WITHDRAW_AMOUNT    = 0.25 * INITIAL_BALANCE   # withdraw $460 each milestone

def run_backtest(enable_withdrawals):
    open_, high_, low_, close_ = df['open'].values, df['high'].values, df['low'].values, df['close'].values
    dhigh_ = df['donch_high_20'].values
    dlow_  = df['donch_low_10'].values
    atr_   = df['atr14'].values
    reg_   = df['regime_up'].values
    slope_ = df['d_ema200_up'].values
    dates_ = df.index
    n      = len(df)

    account = INITIAL_BALANCE
    trades  = []
    withdrawals = []
    total_withdrawn = 0.0
    next_milestone = INITIAL_BALANCE * 2     # first milestone at +100% = $3,678

    in_trade = False
    units = []
    original_entry = original_atr = common_stop = hard_stop = acct_at_entry = None
    pending_exit = False
    pending_exit_reason = None

    def total_size(): return sum(u['size'] for u in units)
    def total_notional(p): return sum(u['size']*p for u in units)
    def total_pnl_at(p): return sum((p - u['entry_price'])*u['size'] for u in units)

    def check_withdrawals(i):
        nonlocal account, total_withdrawn, next_milestone
        if not enable_withdrawals:
            return
        while account >= next_milestone:
            account         -= WITHDRAW_AMOUNT
            total_withdrawn += WITHDRAW_AMOUNT
            withdrawals.append({
                'date':        dates_[i],
                'milestone':   next_milestone,
                'withdrawn':   WITHDRAW_AMOUNT,
                'total_out':   total_withdrawn,
                'acct_after':  account,
            })
            next_milestone += WITHDRAW_INCREMENT

    def close_all(exit_px, reason, i):
        nonlocal account, in_trade, units, original_entry, original_atr, common_stop, hard_stop, acct_at_entry
        total_pnl = total_pnl_at(exit_px)
        avg_entry = sum(u['entry_price']*u['size'] for u in units) / total_size()
        account += total_pnl
        trades.append({
            'entry_date': dates_[units[0]['entry_bar']], 'exit_date': dates_[i],
            'first_entry_price': units[0]['entry_price'], 'avg_entry_price': avg_entry,
            'exit_price': exit_px, 'num_units': len(units),
            'first_unit_risk': acct_at_entry * RISK_PCT,
            'pnl_usd': total_pnl, 'pnl_pct': total_pnl/acct_at_entry*100,
            'R_total': total_pnl / (acct_at_entry * RISK_PCT),
            'duration_h': (i - units[0]['entry_bar'])*4,
            'exit_reason': reason, 'account': account, 'total_withdrawn': total_withdrawn,
        })
        in_trade = False
        units = []
        original_entry = original_atr = common_stop = hard_stop = acct_at_entry = None
        check_withdrawals(i)

    for i in range(WARMUP, n - 1):
        if pending_exit:
            close_all(open_[i], pending_exit_reason, i)
            pending_exit = False
            pending_exit_reason = None

        if in_trade:
            if total_pnl_at(low_[i]) <= -HARD_STOP_PCT * acct_at_entry:
                target_loss = -HARD_STOP_PCT * acct_at_entry
                wavg_entry  = sum(u['entry_price']*u['size'] for u in units) / total_size()
                exit_px     = wavg_entry + target_loss / total_size()
                close_all(exit_px, 'hard_stop_5pct', i)
                continue
            if low_[i] <= common_stop:
                close_all(common_stop, 'atr_stop_trailing', i)
                continue
            while len(units) < MAX_UNITS:
                next_trigger = original_entry + PYRAMID_STEP * len(units) * original_atr
                if high_[i] < next_trigger: break
                unit_entry = next_trigger
                r_amt = acct_at_entry * RISK_PCT
                size  = r_amt / (2 * original_atr)
                lev   = (total_notional(close_[i]) + size*unit_entry) / (account if account > 0 else 1)
                if lev > MAX_LEVERAGE: break
                units.append({'entry_price': unit_entry, 'size': size, 'entry_bar': i})
                new_stop = unit_entry - 2*original_atr
                if new_stop > common_stop: common_stop = new_stop
                target_loss = -HARD_STOP_PCT * acct_at_entry
                wavg_entry  = sum(u['entry_price']*u['size'] for u in units) / total_size()
                hard_stop   = wavg_entry + target_loss / total_size()
            if close_[i] < dlow_[i]:
                pending_exit = True
                pending_exit_reason = 'donchian_exit'
                continue
        else:
            if np.isnan(dhigh_[i]) or np.isnan(atr_[i]) or np.isnan(reg_[i]): continue
            if not (close_[i] > dhigh_[i] and reg_[i]): continue
            if pd.isna(slope_[i]) or not slope_[i]: continue
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
        close_all(close_[n-1], 'still_open_at_end', n-1)

    return pd.DataFrame(trades), pd.DataFrame(withdrawals), account, total_withdrawn

# ── Run both versions ─────────────────────────────────────────────────────────

print("Running Quattro WITHOUT withdrawals (baseline)...")
r0, _,  final0, _              = run_backtest(False)
print("Running Quattro WITH withdrawals (25% of starting capital every 100% milestone)...")
r1, withdraws, final1, total_w = run_backtest(True)

# ── Stats ─────────────────────────────────────────────────────────────────────

def metrics(r, final, total_w=0):
    wins = r[r['R_total'] > 0]; losses = r[r['R_total'] <= 0]
    curve = [INITIAL_BALANCE] + list(r['account'])
    peak = INITIAL_BALANCE; max_dd = 0.0
    for v in curve:
        if v > peak: peak = v
        dd = (v - peak)/peak*100
        if dd < max_dd: max_dd = dd
    max_l = cur_l = 0
    for w in (r['R_total'] > 0):
        if w: cur_l = 0
        else: cur_l += 1; max_l = max(max_l, cur_l)
    total_value = final + total_w
    return {
        'trades': len(r),
        'win_rate': len(wins)/len(r)*100,
        'avg_win_R': wins['R_total'].mean(),
        'avg_loss_R': losses['R_total'].mean(),
        'expectancy': r['R_total'].mean(),
        'max_dd': max_dd,
        'final': final,
        'total_withdrawn': total_w,
        'total_value': total_value,
        'return_pct_balance': (final/INITIAL_BALANCE-1)*100,
        'return_pct_total':   (total_value/INITIAL_BALANCE-1)*100,
        'biggest': r['R_total'].max(),
    }

s0 = metrics(r0, final0, 0)
s1 = metrics(r1, final1, total_w)

sep = "─" * 78
print(f"\n{'═'*78}")
print(f"  Quattro WITHDRAWAL COMPARISON   BTC 4H   Jan 2022 → 2026-05-16")
print(f"{'═'*78}")
print(f"  {'Metric':<32}{'No withdrawals':>20}{'With withdrawals':>20}")
print(sep)
print(f"  {'Total trades':<32}{s0['trades']:>20}{s1['trades']:>20}")
print(f"  {'Win rate %':<32}{s0['win_rate']:>20.1f}{s1['win_rate']:>20.1f}")
print(f"  {'Expectancy (R)':<32}{s0['expectancy']:>+20.3f}{s1['expectancy']:>+20.3f}")
print(f"  {'Max drawdown %':<32}{s0['max_dd']:>+20.2f}{s1['max_dd']:>+20.2f}")
print(f"  {'Biggest winner (R)':<32}{s0['biggest']:>+20.2f}{s1['biggest']:>+20.2f}")
print(sep)
print(f"  {'Final BloFin balance ($)':<32}{s0['final']:>20,.2f}{s1['final']:>20,.2f}")
print(f"  {'Total withdrawn (cold storage)':<32}{s0['total_withdrawn']:>20,.2f}{s1['total_withdrawn']:>20,.2f}")
print(f"  {'TOTAL VALUE (cold + BloFin)':<32}{s0['total_value']:>20,.2f}{s1['total_value']:>20,.2f}")
print(f"  {'Return on starting capital %':<32}{s0['return_pct_total']:>+20.1f}{s1['return_pct_total']:>+20.1f}")
print(f"  {'Number of withdrawals':<32}{0:>20}{len(withdraws):>20}")

print(f"\n{sep}")
print(f"  WITHDRAWAL HISTORY")
print(sep)
if len(withdraws) > 0:
    print(f"  {'Date':<12}{'Milestone':>15}{'Withdrawn':>15}{'Total Out':>15}{'Acct After':>15}")
    for _, w in withdraws.iterrows():
        print(f"  {w['date'].strftime('%Y-%m-%d'):<12}${w['milestone']:>13,.0f}${w['withdrawn']:>13,.0f}${w['total_out']:>13,.0f}${w['acct_after']:>13,.0f}")

# ── Equity curve chart ───────────────────────────────────────────────────────

def make_curve(r):
    return pd.DataFrame({
        'date':    [r['entry_date'].iloc[0] - pd.Timedelta(days=1)] + r['exit_date'].tolist(),
        'balance': [INITIAL_BALANCE] + r['account'].tolist(),
        'total_w': [0] + (r['total_withdrawn'] if 'total_withdrawn' in r.columns else [0]*len(r)).tolist(),
    })

c0 = make_curve(r0)
c1 = make_curve(r1)
c1['total_value'] = c1['balance'] + c1['total_w']

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 9),
                                gridspec_kw={'height_ratios':[3, 2]},
                                sharex=True)

ax1.plot(c0['date'], c0['balance'], color='#1f77b4', linewidth=1.5,
         label=f"No withdrawals  (+{s0['return_pct_total']:.0f}%  DD {s0['max_dd']:.1f}%)")
ax1.plot(c1['date'], c1['balance'], color='#ff7f0e', linewidth=1.5,
         label=f"With withdrawals - BloFin balance  (+{(s1['final']/INITIAL_BALANCE-1)*100:.0f}%  DD {s1['max_dd']:.1f}%)")
ax1.plot(c1['date'], c1['total_value'], color='#2ca02c', linewidth=1.5, linestyle='--',
         label=f"With withdrawals - TOTAL (BloFin+cold)  (+{s1['return_pct_total']:.0f}%)")

# Mark withdrawal points
if len(withdraws) > 0:
    ax1.scatter(withdraws['date'], withdraws['acct_after'], color='red', s=30, zorder=5, label='Withdrawals')

ax1.axhline(INITIAL_BALANCE, color='gray', linestyle='--', alpha=0.5)
ax1.set_yscale('log')
ax1.set_ylabel('Account ($) — log scale', fontsize=11)
ax1.set_title('Quattro: With Withdrawals vs No Withdrawals  —  BTC 4H Jan 2022 → May 2026',
              fontsize=13, fontweight='bold')
ax1.legend(loc='upper left', fontsize=10)
ax1.grid(True, alpha=0.3)

# Drawdown comparison
def add_dd(c):
    c = c.copy()
    c['peak'] = c['balance'].cummax()
    c['dd']   = (c['balance'] - c['peak']) / c['peak'] * 100
    return c

c0d = add_dd(c0)
c1d = add_dd(c1)
ax2.plot(c0d['date'], c0d['dd'], color='#1f77b4', linewidth=1.0, label='No withdrawals')
ax2.plot(c1d['date'], c1d['dd'], color='#ff7f0e', linewidth=1.0, label='With withdrawals')
ax2.axhline(0, color='black', linewidth=0.5)
ax2.set_ylabel('Drawdown from peak (%)', fontsize=11)
ax2.set_xlabel('Date', fontsize=11)
ax2.set_title('Underwater Curves (drawdown on BloFin balance only)', fontsize=12)
ax2.legend(loc='lower left', fontsize=10)
ax2.grid(True, alpha=0.3)

for ax in [ax1, ax2]:
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

plt.tight_layout()
plt.savefig('withdrawal_comparison.png', dpi=120, bbox_inches='tight')
print(f"\nChart saved -> withdrawal_comparison.png")
