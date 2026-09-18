"""
Compute verified stats for dead strategies from their result CSVs.
Reads each CSV, infers schema, prints standardized metrics.
"""
import pandas as pd
import os

INITIAL_CAPITAL = 1839.17

def detect_columns(df):
    """Detect which columns are entry_date, exit_date, R, pnl, account in this CSV."""
    cols = {c.lower(): c for c in df.columns}
    schema = {}
    for k in ['entry_date','exit_date']:
        if k in cols: schema[k] = cols[k]
    # R or R_total
    if 'r' in cols: schema['R'] = cols['r']
    elif 'r_total' in cols: schema['R'] = cols['r_total']
    # pnl
    for k in ['pnl_usd','pnl','total_pnl']:
        if k in cols:
            schema['pnl'] = cols[k]; break
    # account or equity
    for k in ['account','equity','balance']:
        if k in cols:
            schema['account'] = cols[k]; break
    return schema

def stats_for(file_path, label):
    if not os.path.exists(file_path):
        print(f"\n=== {label} ===")
        print(f"  FILE NOT FOUND: {file_path}")
        return
    df = pd.read_csv(file_path)
    if len(df) == 0:
        print(f"\n=== {label} ===")
        print(f"  CSV is empty")
        return
    schema = detect_columns(df)
    print(f"\n=== {label} ===")
    print(f"  File: {os.path.basename(file_path)}")
    print(f"  Columns: {list(df.columns)}")
    print(f"  Total trades: {len(df)}")

    # Try R-based
    if 'R' in schema:
        r = df[schema['R']]
        wins = (r > 0).sum(); losses = (r <= 0).sum()
        wr = wins/len(r)*100 if len(r) else 0
        avg_win = r[r>0].mean() if wins > 0 else 0
        avg_loss = r[r<=0].mean() if losses > 0 else 0
        print(f"  Wins/Losses: {wins} / {losses}")
        print(f"  Win rate: {wr:.1f}%")
        print(f"  Avg win R: {avg_win:+.3f}, Avg loss R: {avg_loss:+.3f}")
        print(f"  Expectancy: {r.mean():+.3f}R")
        print(f"  Best R: {r.max():+.2f}, Worst R: {r.min():+.2f}")
        print(f"  Total R: {r.sum():+.2f}")

    # Dates
    if 'entry_date' in schema and 'exit_date' in schema:
        df[schema['entry_date']] = pd.to_datetime(df[schema['entry_date']], errors='coerce')
        df[schema['exit_date']]  = pd.to_datetime(df[schema['exit_date']], errors='coerce')
        first = df[schema['entry_date']].min()
        last  = df[schema['exit_date']].max()
        if pd.notna(first) and pd.notna(last):
            days = (last - first).days
            print(f"  Period: {first.date()} -> {last.date()} ({days} days, {days/365.25:.2f} years)")

    # Account-based metrics
    if 'account' in schema:
        eq = df[schema['account']]
        eq_clean = eq.dropna()
        if len(eq_clean) > 0:
            # Find starting capital
            if 'pnl' in schema:
                start = eq_clean.iloc[0] - df[schema['pnl']].iloc[0]
            else:
                start = INITIAL_CAPITAL
            final = eq_clean.iloc[-1]
            total_ret = (final/start - 1)*100
            print(f"  Starting: ${start:,.2f}  Final: ${final:,.2f}  Return: {total_ret:+.1f}%")
            if 'entry_date' in schema and 'exit_date' in schema and pd.notna(first) and pd.notna(last):
                yrs = days/365.25
                if yrs > 0:
                    apy = ((final/start) ** (1/yrs) - 1) * 100
                    print(f"  APY: {apy:+.1f}%")
            # Max DD
            peak = start; mdd = 0
            for v in eq_clean:
                if v > peak: peak = v
                d = (v-peak)/peak*100
                if d < mdd: mdd = d
            print(f"  Max DD: {mdd:.2f}%")

    # Year breakdown if dates available
    if 'entry_date' in schema and pd.api.types.is_datetime64_any_dtype(df[schema['entry_date']]):
        df['_year'] = df[schema['entry_date']].dt.year
        per_year = df.groupby('_year').size()
        print(f"  Trades per year:")
        for yr, n in per_year.items():
            print(f"    {int(yr)}: {n}")

# ── Bear Edge — 2 variants ──
stats_for("../3_dead_strategies/bear_edge/backtest_bearedge_A_nofilter.csv", "Bear Edge A (no filter)")
stats_for("../3_dead_strategies/bear_edge/backtest_bearedge_B_thu_sat.csv",  "Bear Edge B (Thu-Sat only)")

# ── Setup A Spring — main variants ──
stats_for("../3_dead_strategies/setup_a_spring/setupA_trades_4h.csv",         "Setup A Spring 4H (full)")
stats_for("../3_dead_strategies/setup_a_spring/setupA_curated_4h_trades.csv", "Setup A Spring 4H (curated)")
stats_for("../3_dead_strategies/setup_a_spring/setupA_trades.csv",            "Setup A Spring (small)")

# ── Setup A on 1H — fees destroy it ──
stats_for("../3_dead_strategies/setup_a_1h_pyramid/setupA_trades_1h.csv", "Setup A on 1H")
stats_for("../3_dead_strategies/setup_a_1h_pyramid/setupA_trades_1d.csv", "Setup A on 1D (reference)")

# ── Counterpunch — 3 variants ──
stats_for("../3_dead_strategies/counterpunch/backtest_counterpunch_A_noregime.csv",   "Counterpunch A (no regime)")
stats_for("../3_dead_strategies/counterpunch/backtest_counterpunch_B_quattro_off.csv","Counterpunch B (Quattro off)")
stats_for("../3_dead_strategies/counterpunch/backtest_counterpunch_C_quattro_on.csv", "Counterpunch C (Quattro on)")
