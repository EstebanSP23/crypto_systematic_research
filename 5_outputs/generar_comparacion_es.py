"""Generar gráfico comparativo de los 3 modos para audiencia no técnica."""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle

INITIAL_BALANCE = 1839.17

r0 = pd.read_csv('../2_strategies/01_quattro_donchian/backtest_trend_results.csv')
r2 = pd.read_csv('../2_strategies/01_quattro_donchian/backtest_pyramid_2units_results.csv')
r4 = pd.read_csv('../2_strategies/01_quattro_donchian/backtest_donchian_pyramid_results.csv')

for r in (r0, r2, r4):
    r['entry_date'] = pd.to_datetime(r['entry_date'])
    r['exit_date']  = pd.to_datetime(r['exit_date'])

def equity_curve(r):
    return pd.DataFrame({
        'date':    [r['entry_date'].iloc[0] - pd.Timedelta(days=1)] + r['exit_date'].tolist(),
        'balance': [INITIAL_BALANCE] + r['account'].tolist(),
    })

c0 = equity_curve(r0)
c2 = equity_curve(r2)
c4 = equity_curve(r4)

# Stats por modo
def stats(r):
    curve = [INITIAL_BALANCE] + list(r['account'])
    peak  = INITIAL_BALANCE; max_dd = 0
    for v in curve:
        if v > peak: peak = v
        dd = (v - peak)/peak*100
        if dd < max_dd: max_dd = dd
    return {'final': r['account'].iloc[-1], 'dd': max_dd,
            'ret': (r['account'].iloc[-1]/INITIAL_BALANCE - 1)*100,
            'trades': len(r)}

s0, s2, s4 = stats(r0), stats(r2), stats(r4)

# ── GRÁFICO ───────────────────────────────────────────────────────────────────

fig = plt.figure(figsize=(14, 11))
gs  = fig.add_gridspec(3, 3, height_ratios=[2.2, 1, 1], hspace=0.45, wspace=0.3)

# Curvas de capital
ax_top = fig.add_subplot(gs[0, :])
colors = {'cons':'#2ecc71', 'mod':'#f39c12', 'agg':'#e74c3c'}
ax_top.plot(c0['date'], c0['balance'], color=colors['cons'], linewidth=2,
            label=f"Conservador  +{s0['ret']:.0f}%   (caída máx {s0['dd']:.0f}%)")
ax_top.plot(c2['date'], c2['balance'], color=colors['mod'], linewidth=2,
            label=f"Moderado  +{s2['ret']:.0f}%   (caída máx {s2['dd']:.0f}%)")
ax_top.plot(c4['date'], c4['balance'], color=colors['agg'], linewidth=2,
            label=f"Agresivo  +{s4['ret']:.0f}%   (caída máx {s4['dd']:.0f}%)")
ax_top.axhline(INITIAL_BALANCE, color='gray', linestyle='--', alpha=0.4, label=f'Capital inicial ${INITIAL_BALANCE:,.0f}')
ax_top.set_yscale('log')
ax_top.set_ylabel('Cuenta (USD)', fontsize=12)
ax_top.set_title('Estrategia Quattro — Comparación de los 3 Modos\n(Bitcoin, Enero 2022 → Mayo 2026)',
                 fontsize=14, fontweight='bold')
ax_top.legend(loc='upper left', fontsize=11, framealpha=0.95)
ax_top.grid(True, alpha=0.3)
ax_top.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
ax_top.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
plt.setp(ax_top.xaxis.get_majorticklabels(), rotation=45, ha='right')

# Barras: ganancia total
ax1 = fig.add_subplot(gs[1, 0])
modes  = ['Conservador', 'Moderado', 'Agresivo']
returns = [s0['ret'], s2['ret'], s4['ret']]
bars = ax1.bar(modes, returns, color=[colors['cons'], colors['mod'], colors['agg']], edgecolor='black', linewidth=0.5)
ax1.set_title('Ganancia Total (%)', fontsize=11, fontweight='bold')
ax1.set_ylabel('%')
for bar, v in zip(bars, returns):
    ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 30, f'+{v:.0f}%',
             ha='center', fontsize=11, fontweight='bold')
ax1.grid(True, alpha=0.3, axis='y')
ax1.set_ylim(0, max(returns) * 1.15)

# Barras: caída máxima
ax2 = fig.add_subplot(gs[1, 1])
dds = [abs(s0['dd']), abs(s2['dd']), abs(s4['dd'])]
bars = ax2.bar(modes, dds, color=[colors['cons'], colors['mod'], colors['agg']], edgecolor='black', linewidth=0.5)
ax2.set_title('Caída Máxima (%)\n(qué tanto baja la cuenta en su peor momento)', fontsize=11, fontweight='bold')
ax2.set_ylabel('%')
for bar, v in zip(bars, dds):
    ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.8, f'-{v:.0f}%',
             ha='center', fontsize=11, fontweight='bold', color='darkred')
ax2.grid(True, alpha=0.3, axis='y')
ax2.set_ylim(0, max(dds) * 1.20)

# Barras: balance final
ax3 = fig.add_subplot(gs[1, 2])
finals = [s0['final'], s2['final'], s4['final']]
bars = ax3.bar(modes, finals, color=[colors['cons'], colors['mod'], colors['agg']], edgecolor='black', linewidth=0.5)
ax3.set_title(f'Balance Final\n(empezando con ${INITIAL_BALANCE:,.0f})', fontsize=11, fontweight='bold')
ax3.set_ylabel('USD')
for bar, v in zip(bars, finals):
    ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 500, f'${v:,.0f}',
             ha='center', fontsize=11, fontweight='bold')
ax3.grid(True, alpha=0.3, axis='y')
ax3.set_ylim(0, max(finals) * 1.15)

# Texto explicativo
ax_text = fig.add_subplot(gs[2, :])
ax_text.axis('off')
explanation = (
    "Los 3 modos usan EXACTAMENTE la misma estrategia y la misma señal de entrada — sólo cambia cuántas veces\n"
    "el sistema agrega a una posición ganadora (a esto se le llama 'piramidación').\n\n"
    "• CONSERVADOR: 1 sola posición por operación. Ganancias y pérdidas modestas. Buena para empezar.\n"
    "• MODERADO:   Hasta 2 posiciones por operación. Ganancias y pérdidas DOBLES vs Conservador.\n"
    "• AGRESIVO:   Hasta 4 posiciones por operación. Ganancias enormes pero también mayores caídas en el camino.\n\n"
    "TODOS los modos arriesgan máximo 2% por operación. La diferencia es cuánto se ACUMULA cuando una operación está funcionando.\n"
    "El modo Agresivo gana 10x más que el Conservador, pero exige aguantar caídas de -37% en el camino."
)
ax_text.text(0.02, 0.5, explanation, fontsize=10.5, va='center', family='sans-serif',
             linespacing=1.4)

plt.savefig('quattro_comparacion_es.png', dpi=140, bbox_inches='tight', facecolor='white')
print("Guardado: quattro_comparacion_es.png")
