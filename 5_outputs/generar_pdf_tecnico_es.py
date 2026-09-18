"""Especificación técnica de Quattro en español — PDF detallado."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    Preformatted, KeepTogether,
)

OUTPUT = "quattro_tecnico_es.pdf"

doc = SimpleDocTemplate(
    OUTPUT, pagesize=letter,
    leftMargin=0.7*inch, rightMargin=0.7*inch,
    topMargin=0.6*inch,  bottomMargin=0.6*inch,
)

styles = getSampleStyleSheet()

title_style = ParagraphStyle('T', parent=styles['Title'], fontSize=20,
    textColor=colors.HexColor('#1a1a1a'), alignment=TA_CENTER, spaceAfter=4, leading=24)
subtitle = ParagraphStyle('Sub', parent=styles['Normal'], fontSize=11,
    textColor=colors.HexColor('#666666'), alignment=TA_CENTER, spaceAfter=12)
h1 = ParagraphStyle('H1', parent=styles['Heading1'], fontSize=16,
    textColor=colors.HexColor('#1a1a1a'), spaceBefore=14, spaceAfter=8)
h2 = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=13,
    textColor=colors.HexColor('#2c3e50'), spaceBefore=10, spaceAfter=5)
h3 = ParagraphStyle('H3', parent=styles['Heading3'], fontSize=11,
    textColor=colors.HexColor('#34495e'), spaceBefore=6, spaceAfter=3)
body = ParagraphStyle('B', parent=styles['Normal'], fontSize=10,
    alignment=TA_JUSTIFY, leading=13, spaceAfter=5)
body_left = ParagraphStyle('BL', parent=styles['Normal'], fontSize=10,
    alignment=TA_LEFT, leading=13, spaceAfter=5)
small = ParagraphStyle('Sm', parent=styles['Normal'], fontSize=9,
    leading=12, spaceAfter=3)
code = ParagraphStyle('Code', parent=styles['Code'], fontSize=8.5,
    leading=11, leftIndent=10, rightIndent=10, spaceAfter=8, spaceBefore=4,
    backColor=colors.HexColor('#f4f4f4'), borderColor=colors.HexColor('#dddddd'),
    borderWidth=0.5, borderPadding=6, textColor=colors.HexColor('#1a1a1a'))
footer = ParagraphStyle('F', parent=styles['Normal'], fontSize=8,
    textColor=colors.HexColor('#888888'), alignment=TA_CENTER)

S = []

# ── PORTADA ───────────────────────────────────────────────────────────────────
S.append(Spacer(1, 80))
S.append(Paragraph("Quattro", title_style))
S.append(Paragraph("Especificación Técnica Detallada", subtitle))
S.append(Spacer(1, 30))
S.append(Paragraph(
    "Estrategia de trading automatizada para Bitcoin perpetuos en BloFin. "
    "Donchian breakout con piramidación al estilo Turtle, filtro de régimen "
    "por EMA 200 diaria, y gestión de riesgo basada en ATR.",
    body))
S.append(Spacer(1, 12))
S.append(Paragraph(
    "Este documento cubre la lógica de la estrategia, las matemáticas detrás "
    "de la piramidación y los stops, la metodología del backtest, el análisis "
    "de riesgo, la arquitectura del bot y las limitaciones conocidas.",
    body))
S.append(Spacer(1, 120))
S.append(Paragraph("Versión 1.0 — Mayo 2026", footer))

S.append(PageBreak())

# ── 1. OVERVIEW ───────────────────────────────────────────────────────────────
S.append(Paragraph("1. Visión General", h1))
S.append(Paragraph(
    "Quattro es una estrategia de <b>seguimiento de tendencia, solo larga, con "
    "piramidación</b> sobre BTC/USDT perpetuo, ejecutada en timeframe de 4 horas "
    "vía un bot Python corriendo 24/7 en un VPS de Frankfurt, conectado a BloFin "
    "vía CCXT.", body))
S.append(Paragraph(
    "<b>Genealogía:</b> ruptura de canal Donchian (Richard Donchian, ~1960s) + "
    "piramidación Turtle (Dennis y Eckhardt, 1983) + filtro de régimen "
    "(literatura moderna de equity long-only, e.g., Faber 2007).", body))
S.append(Paragraph(
    "<b>Tesis del edge:</b> distribución de retornos con cola derecha gruesa. "
    "Tasa de acierto ~27%, pero la cola derecha (ganadores &gt;10R durante tendencias "
    "alcistas sostenidas) carga todo el P&amp;L. Las estrategias de mean reversion "
    "tienen la forma opuesta: alta tasa de acierto, sin cola.", body))

# ── 2. ESPECIFICACIÓN DE LA ESTRATEGIA ────────────────────────────────────────
S.append(Paragraph("2. Especificación de la Estrategia", h1))

S.append(Paragraph("2.1 Condiciones de Entrada", h2))
S.append(Paragraph(
    "Al cierre de cada vela de 4H, <b>TODAS</b> las siguientes condiciones deben "
    "cumplirse:", body))
S.append(Preformatted(
    "1. close[t] > max(high[t-20 : t-1])            # Ruptura Donchian-20 (excl. vela actual)\n"
    "2. close[t] > daily_EMA_200                    # Filtro de régimen — precio sobre tendencia LTF\n"
    "3. daily_EMA_200[d] > daily_EMA_200[d-20]      # Filtro de pendiente — tendencia LTF subiendo",
    code))
S.append(Paragraph(
    "Si las tres son verdaderas → entrar en largo al <code>open[t+1]</code> "
    "(apertura de la siguiente vela).", body))
S.append(Paragraph(
    "El filtro de pendiente lo añadimos durante la fase de optimización. Bloquea "
    "entradas en condiciones tipo \"BTC sobre la EMA 200 pero la EMA misma está "
    "plana\" (la mayor parte de la segunda mitad de 2022 y el chop de finales de "
    "2024). Empíricamente mejoró la expectancy de +0.542R a +0.561R y evitó "
    "las peores entradas del drawdown de 2024.", body))

S.append(Paragraph("2.2 Dimensionamiento de Posición", h2))
S.append(Preformatted(
    "R = INITIAL_CAPITAL × 0.02              # Riesgo por unidad en dólares\n"
    "N = ATR(14)[t]                          # ATR de Wilder en la vela de señal\n"
    "stop_distance = 2 × N                   # Distancia al stop en dólares\n"
    "unit_size_BTC = R / stop_distance       # Tamaño de la Unit 1 en BTC",
    code))
S.append(Paragraph(
    "R y N son <b>fijos durante todo el ciclo de vida del trade</b> — no se "
    "recalculan a medida que avanza el trade (esta es la regla clásica de los "
    "Turtles; el bot usa el mismo valor de N para las 4 unidades incluso si el "
    "ATR de 4H cambia durante el trade).", body))

S.append(Paragraph("2.3 Piramidación", h2))
S.append(Paragraph(
    "Después de que Unit 1 entra al precio <code>E</code>:", body))

pyr_table = [
    ['Unidad', 'Precio de Trigger', 'Método de Activación'],
    ['2', 'E + 0.5N', 'Stop-buy reposando en el exchange'],
    ['3', 'E + 1.0N', 'Stop-buy reposando en el exchange'],
    ['4', 'E + 1.5N', 'Stop-buy reposando en el exchange'],
]
t = Table(pyr_table, colWidths=[0.8*inch, 1.6*inch, 3.5*inch])
t.setStyle(TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
    ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
    ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
    ('FONTSIZE',   (0, 0), (-1, -1), 9.5),
    ('GRID',       (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
    ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f5f5f5'), colors.white]),
    ('TOPPADDING',   (0, 0), (-1, -1), 5),
    ('BOTTOMPADDING',(0, 0), (-1, -1), 5),
]))
S.append(t)
S.append(Spacer(1, 6))
S.append(Paragraph(
    "Cada unidad tiene el <b>mismo riesgo en dólares</b> (R = $10 con capital de "
    "$500) y el <b>mismo tamaño en BTC</b> (<code>R / 2N</code>). El bot calcula "
    "las tres unidades de antemano y coloca todas las órdenes stop-buy en BloFin "
    "al momento de la entrada. El exchange las dispara intra-vela en el instante "
    "que el precio toca cada trigger.", body))

S.append(Paragraph("2.4 Gestión de Stops", h2))
S.append(Paragraph(
    "Dos stops simultáneos, ambos basados en mecha (wick-based, órdenes "
    "stop-market gestionadas por el exchange):", body))

S.append(Paragraph("Stop trailing 2×ATR:", h3))
S.append(Preformatted(
    "Inicial:           entry - 2N\n"
    "Trailing al añadir nueva unidad:  newest_unit_entry - 2N\n"
    "Nunca baja.",
    code))

S.append(Paragraph("Hard stop al 5% de la cuenta:", h3))
S.append(Preformatted(
    "Inicial:    entry - (HARD_STOP_PCT × account / unit_size)\n"
    "\n"
    "Recalculado en cada adición de unidad:\n"
    "  weighted_avg_entry = Σ(entry_i × size_i) / total_size\n"
    "  target_loss        = -0.05 × acct_at_entry\n"
    "  hard_stop_price    = weighted_avg_entry + (target_loss / total_size)",
    code))

S.append(Paragraph(
    "<b>La convergencia:</b> en 4 unidades, ambos stops convergen exactamente al "
    "mismo precio.", body))
S.append(Paragraph("Demostración — si las 4 unidades se disparan en intervalos de +0.5N:", body))
S.append(Preformatted(
    "Entradas:       E, E+0.5N, E+1.0N, E+1.5N\n"
    "Trailing stop después de Unit 4 = (E + 1.5N) - 2N = E - 0.5N\n"
    "\n"
    "P&L por unidad si exit en E - 0.5N:\n"
    "  Unit 1:  -0.5N × s = -0.25R\n"
    "  Unit 2:  -1.0N × s = -0.50R\n"
    "  Unit 3:  -1.5N × s = -0.75R\n"
    "  Unit 4:  -2.0N × s = -1.00R\n"
    "                       ─────\n"
    "  Total =              -2.50R  =  -5%      (donde s = R/2N)",
    code))
S.append(Paragraph(
    "Esto no es coincidencia — el hard stop del 5% está <b>específicamente "
    "calibrado</b> para ser el peor caso cuando estás completamente piramidado.",
    body))

S.append(Paragraph("2.5 Condiciones de Salida", h2))
S.append(Paragraph(
    "Tres triggers de salida independientes, todos evaluados contra la misma "
    "posición:", body))

S.append(Paragraph("Salida primaria trailing (basada en cierre):", h3))
S.append(Preformatted(
    "close[t] < min(low[t-10 : t-1])    # Ruptura bajista Donchian-10",
    code))
S.append(Paragraph(
    "Dispara al open de la siguiente vela vía orden de mercado. Esto es lo que "
    "asegura las ganancias de tendencia.", body))

S.append(Paragraph("Stop catástrofe 2×ATR (basado en mecha):", h3))
S.append(Paragraph(
    "Orden stop-market sell gestionada por el exchange al nivel de trailing actual. "
    "Dispara intra-vela en el instante que el precio toca.", body))

S.append(Paragraph("Hard stop 5% (basado en mecha):", h3))
S.append(Paragraph(
    "Orden stop-market sell gestionada por el exchange al nivel recalculado de "
    "hard stop. Mismo mecanismo.", body))
S.append(Paragraph(
    "Cualquiera de los stops que dispare → el exchange gestiona la ejecución → "
    "el bot reconcilia en la siguiente iteración.", body))

S.append(PageBreak())

# ── 3. LOS 3 MODOS ────────────────────────────────────────────────────────────
S.append(Paragraph("3. Los 3 Modos", h1))
S.append(Paragraph(
    "El único parámetro que varía es <code>MAX_UNITS</code>. Todo lo demás "
    "(entrada, sizing por unidad, stops, filtro de régimen) es idéntico.", body))

modes = [
    ['Parámetro', 'Conservador', 'Moderado', 'Agresivo'],
    ['MAX_UNITS', '1', '2', '4'],
    ['RISK_PCT', '0.02', '0.02', '0.02'],
    ['ATR_STOP_MULT', '2.0', '2.0', '2.0'],
    ['PYRAMID_STEP', 'n/a', '0.5N', '0.5N'],
    ['HARD_STOP_PCT', '0.05', '0.05', '0.05'],
]
mt = Table(modes, colWidths=[2.0*inch, 1.3*inch, 1.3*inch, 1.3*inch])
mt.setStyle(TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
    ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
    ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
    ('FONTSIZE',   (0, 0), (-1, -1), 9.5),
    ('GRID',       (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
    ('ALIGN',      (1, 0), (-1, -1), 'CENTER'),
    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f5f5f5'), colors.white]),
    ('TOPPADDING',   (0, 0), (-1, -1), 5),
    ('BOTTOMPADDING',(0, 0), (-1, -1), 5),
]))
S.append(mt)

S.append(Spacer(1, 8))
S.append(Paragraph("Implicaciones matemáticas:", h3))

metrics = [
    ['Métrica', 'Conservador', 'Moderado', 'Agresivo'],
    ['Win rate', '32.6%', '29.7%', '26.6%'],
    ['Avg win (R)', '+3.39', '+6.97', '+13.42'],
    ['Avg loss (R)', '-0.83', '-1.48', '-2.01'],
    ['Expectancy', '+0.542R', '+1.029R', '+2.097R'],
    ['Max drawdown', '-15.4%', '-27.3%', '-37.5%'],
    ['Retorno total', '+127%', '+296%', '+1,107%'],
    ['Profit factor', '2.34', '2.42', '2.85'],
    ['Ratio Retorno/DD', '8.21', '10.82', '29.52'],
]
mt2 = Table(metrics, colWidths=[2.0*inch, 1.3*inch, 1.3*inch, 1.3*inch])
mt2.setStyle(TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
    ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
    ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
    ('FONTSIZE',   (0, 0), (-1, -1), 9.5),
    ('GRID',       (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
    ('ALIGN',      (1, 0), (-1, -1), 'CENTER'),
    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f5f5f5'), colors.white]),
    ('TOPPADDING',   (0, 0), (-1, -1), 5),
    ('BOTTOMPADDING',(0, 0), (-1, -1), 5),
    ('FONTNAME',   (0, 4), (-1, 4), 'Helvetica-Bold'),    # Expectancy bold
]))
S.append(mt2)

S.append(Spacer(1, 8))
S.append(Paragraph("Lectura de los números:", h3))
S.append(Paragraph(
    "Un <code>MAX_UNITS</code> más bajo trunca la cola derecha de la distribución. "
    "El avg win se reduce proporcionalmente; el avg loss también se reduce (porque "
    "los perdedores piramidados consumen más R). El drawdown se reduce más o menos "
    "linealmente. El retorno total escala de forma superlineal con MAX_UNITS porque "
    "las pocas tendencias gigantes compounden mucho más fuerte cuando están "
    "completamente piramidadas.", body))
S.append(Paragraph(
    "Cuál es el \"mejor\" modo según ratios tipo Sharpe es debatible. Por el ratio "
    "Retorno/DD, Agresivo gana por un margen amplio (29.5 vs 10.8 vs 8.2) — pero "
    "ese ratio recompensa desproporcionadamente a los pocos ganadores enormes. "
    "Por experiencia emocional, Moderado es el ajuste más limpio.", body))

S.append(PageBreak())

# ── 4. METODOLOGÍA DEL BACKTEST ───────────────────────────────────────────────
S.append(Paragraph("4. Metodología del Backtest", h1))

S.append(Paragraph("4.1 Datos", h2))
S.append(Paragraph(
    "<b>Fuente:</b> Binance BTC/USDT (spot) vía CCXT<br/>"
    "<b>Timeframes:</b> 4H (38,322 velas) + 1D (1,962 velas)<br/>"
    "<b>Período:</b> 2022-01-01 hasta 2026-05-16 (4.4 años)<br/>"
    "<b>Warmup de la EMA 200 diaria:</b> 200 velas diarias antes del 2022-01-01 "
    "(es decir, datos desde ~2021-06)", body))

S.append(Paragraph("4.2 Cálculo de Indicadores", h2))
S.append(Paragraph(
    "• <b>EMA:</b> <code>pandas.Series.ewm(span=N, adjust=False).mean()</code> — "
    "coincide con Pine Script <code>ta.ema()</code><br/>"
    "• <b>SMA:</b> <code>rolling(N).mean()</code><br/>"
    "• <b>ATR(14):</b> Suavizado de Wilder vía "
    "<code>tr.ewm(alpha=1/14, adjust=False).mean()</code> — coincide con Pine "
    "Script <code>ta.atr()</code><br/>"
    "• <b>Donchian:</b> <code>rolling(N).max().shift(1)</code> y "
    "<code>.min().shift(1)</code> — el <code>shift(1)</code> excluye la vela "
    "actual del lookback (coincide con nuestra regla de entrada)<br/>"
    "• <b>PMARP y BBWP</b> (usados en la estrategia de mean-reversion abandonada) "
    "fueron validados contra las implementaciones Pine Script de The_Caretaker "
    "con una precisión de 0.5% en las mismas velas", body))

S.append(Paragraph("4.3 Supuestos del Motor de Backtest", h2))
S.append(Paragraph(
    "• <b>Ejecución de entrada:</b> señal en cierre de vela <code>t</code> → fill "
    "en <code>open[t+1]</code> (apertura de la siguiente vela)<br/>"
    "• <b>Fills de stop:</b> wick-based — si <code>low[t] ≤ stop_level</code>, "
    "exit ejecuta exactamente en <code>stop_level</code> (asume orden stop-market "
    "reposando en el exchange)<br/>"
    "• <b>Fills de pyramid:</b> wick-based — si <code>high[t] ≥ trigger</code>, "
    "fill exactamente en <code>trigger</code><br/>"
    "• <b>Salida Donchian:</b> close-based — <code>close[t] &lt; donch_low_10[t]</code> "
    "→ exit en <code>open[t+1]</code><br/>"
    "• <b>Prioridad de orden dentro de una vela:</b> stops se revisan antes que "
    "pyramids (conservador — asume peor caso para posiciones piramidadas)<br/>"
    "• <b>Slippage:</b> cero (limitación reconocida; en real será ~5-15 bps por "
    "orden de mercado)<br/>"
    "• <b>Comisiones:</b> cero en el backtest actual (en real: BloFin maker 0.02% "
    "/ taker 0.06% = ~$0.012 por round-trip en un trade de $20)<br/>"
    "• <b>Funding rate:</b> cero (en real: ~0.01% por 8h en BTC perp = ~3.6% "
    "anualizado de costo cuando estás largo)", body))
S.append(Paragraph(
    "El impacto acumulado de comisiones + funding en el backtest Agresivo es "
    "aproximadamente -5 a -10 puntos porcentuales en 4.4 años. No catastrófico, "
    "pero real.", body))

S.append(Paragraph("4.4 Sin Sesgo de Lookahead", h2))
S.append(Paragraph(
    "• La ruptura Donchian usa <code>los 20 bars previos</code> (<code>shift(1)</code>)<br/>"
    "• La salida Donchian usa <code>los 10 bars previos</code> (<code>shift(1)</code>)<br/>"
    "• La EMA 200 diaria se alinea al 4H vía "
    "<code>df_d.index + Timedelta(days=1)</code> seguido de "
    "<code>reindex(method='ffill')</code> — el EMA de una vela diaria solo se "
    "vuelve \"disponible\" al cierre del día (inicio del día siguiente), "
    "previniendo filtración de datos futuros en velas 4H dentro de la vela diaria",
    body))

S.append(PageBreak())

# ── 5. DESCOMPOSICIÓN DE PERFORMANCE ──────────────────────────────────────────
S.append(Paragraph("5. Descomposición de Performance (modo Agresivo)", h1))

S.append(Paragraph("Distribución de R-multiples sobre 94 trades:", h3))
S.append(Preformatted(
    "<-2R              2   ##                      ← hits de hard-stop\n"
    "-2 a -1R         36   ####################################  ← perdedores piramidados\n"
    "-1 a -0.5R        9   #########               ← perdedores de una sola unidad\n"
    "-0.5 a 0R        13   #############\n"
    "0 a 0.5R          3   ###\n"
    "0.5 a 1R          7   #######\n"
    "1 a 2R            5   #####\n"
    "2 a 3R            3   ###\n"
    "3 a 5R            2   ##\n"
    "5 a 10R           4   ####\n"
    ">10R              9   #########                ← cola derecha (aquí está el dinero)",
    code))

S.append(Paragraph("Concentración de ganancias:", h3))
S.append(Paragraph(
    "• <b>Top 5 trades:</b> $30,574 totales ← <b>150% del profit neto</b><br/>"
    "• <b>Top 10 trades:</b> $42,708 ← <b>210% del profit neto</b>", body))
S.append(Paragraph(
    "En otras palabras: resta los 5 mejores trades y habrías <b>perdido</b> dinero "
    "en 4.4 años. Esta es la firma del trend-following.", body))

S.append(Paragraph("Desglose por año:", h3))
year_table = [
    ['Año', 'Trades', 'Win%', 'P&L', 'Nota'],
    ['2022', '1', '0%', '-$92', 'Bear market — filtro de régimen nos mantuvo fuera'],
    ['2023', '30', '23%', '+$5,386', 'Un ganador de 76.67R cargó el año'],
    ['2024', '32', '31%', '+$10,780', 'El año más fuerte'],
    ['2025', '29', '28%', '+$5,197', 'Más choppy; edge más delgado'],
    ['2026 YTD', '2', '0%', '-$915', 'Muestra pequeña'],
]
yt = Table(year_table, colWidths=[0.9*inch, 0.7*inch, 0.7*inch, 1.0*inch, 2.8*inch])
yt.setStyle(TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
    ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
    ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
    ('FONTSIZE',   (0, 0), (-1, -1), 9),
    ('GRID',       (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
    ('ALIGN',      (1, 0), (3, -1), 'CENTER'),
    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f5f5f5'), colors.white]),
    ('TOPPADDING',   (0, 0), (-1, -1), 4),
    ('BOTTOMPADDING',(0, 0), (-1, -1), 4),
]))
S.append(yt)

# ── 6. ANÁLISIS DE RIESGO ─────────────────────────────────────────────────────
S.append(Paragraph("6. Análisis de Riesgo", h1))

S.append(Paragraph(
    "<b>Riesgo por trade:</b> limitado exactamente al 5% vía el hard stop. La peor "
    "pérdida de un solo trade en el backtest = -2.5R = -5% del capital asignado.",
    body))
S.append(Paragraph(
    "<b>Racha de pérdidas consecutivas:</b> máximo 9 en el backtest. A -2R promedio: "
    "~18R = ~36% de drawdown en secuencia. Coincide con el max DD observado de "
    "-37.5% casi exactamente.", body))
S.append(Paragraph(
    "<b>Tail risk (gap-down de BTC):</b> el hard stop es wick-based y gestionado "
    "por el exchange, así que incluso en un flash crash sales cerca de -5% (el "
    "slippage puede empujar a -6 a -8% en extremos). El bot <b>NO PUEDE</b> proteger "
    "contra gaps mayores al apalancamiento efectivo de la posición al precio del "
    "hard-stop (e.g., liquidación de BloFin). El sizing es lo suficientemente "
    "conservador como para que incluso un flash crash de 20% desde la entrada no "
    "liquide (max leverage es ~1.5x con 4 unidades).", body))
S.append(Paragraph(
    "<b>Riesgo de régimen:</b> el filtro EMA 200 + pendiente eliminó 2022 de la "
    "estrategia (1 trade) pero no siempre lo hará. Un \"bear sigiloso\" con breves "
    "mean-reversions sobre la EMA podría disparar entradas que todas fracasen.", body))
S.append(Paragraph(
    "<b>Riesgo de decaimiento de estrategia:</b> los breakouts Donchian han sido "
    "documentados desde los 1960s. Aún funcionan, pero cada ciclo comprime el edge "
    "algo. El +1,107% del Agresivo en 4.4 años es improbable de repetir en 2026-2030 "
    "— ancla las expectativas en quizás 30-50% de eso.", body))

S.append(PageBreak())

# ── 7. ARQUITECTURA DEL BOT ───────────────────────────────────────────────────
S.append(Paragraph("7. Arquitectura del Bot", h1))

S.append(Preformatted(
    "┌──────────────────────────────────────────────────────────────────────┐\n"
    "│  VPS Frankfurt (DigitalOcean, Ubuntu 24.04, 1 vCPU, 1GB RAM)         │\n"
    "│                                                                       │\n"
    "│  ┌────────────────────────────────────────────────────────────┐     │\n"
    "│  │ systemd: quattro.service                                    │     │\n"
    "│  │   ↳ /opt/quattro_bot/venv/bin/python main.py                │     │\n"
    "│  │   ↳ Restart=on-failure, RestartSec=30                       │     │\n"
    "│  └────────────────────────────────────────────────────────────┘     │\n"
    "│                                                                       │\n"
    "│  Módulos:                                                             │\n"
    "│   config.py        — parámetros, carga de .env                       │\n"
    "│   data.py          — fetch de velas 4H + 1D de Binance (CCXT)        │\n"
    "│   indicators.py    — Donchian, ATR, EMA, pendiente                   │\n"
    "│   strategy.py      — lógica de decisión (paths DRY-RUN)              │\n"
    "│   execution.py     — gestión de órdenes BloFin (CCXT)                │\n"
    "│   state.py         — persistencia JSON                               │\n"
    "│   notifications.py — Telegram vía HTTPS                              │\n"
    "│   main.py          — loop principal, reconciliación, hardening      │\n"
    "│                                                                       │\n"
    "│   state.json       — estado persistente (posición, órdenes, etc.)    │\n"
    "│   logs/*.log       — logs mensuales rotativos                        │\n"
    "└──────────────────────────────────────────────────────────────────────┘\n"
    "\n"
    "        ↓ HTTPS (cada 4h)        ↓ HTTPS (continuo)    ↓ HTTPS\n"
    "    ┌─────────────┐         ┌──────────────┐      ┌──────────┐\n"
    "    │ Binance API │         │  BloFin API  │      │ Telegram │\n"
    "    │  (datos)    │         │  (ejecución) │      │   Bot    │\n"
    "    └─────────────┘         └──────────────┘      └──────────┘",
    code))

S.append(Paragraph(
    "<b>Timing del loop:</b> <code>next_4h_close() + 60s</code> — despierta 1 "
    "minuto después de cada cierre de vela 4H de Binance para permitir que la "
    "vela se estabilice en la API.", body))

S.append(Paragraph("Máquina de estados:", h3))
S.append(Preformatted(
    "        ┌──────────┐   señal + filtros + margen OK\n"
    "        │   FLAT   │ ──────────────────────────────► OPEN\n"
    "        │          │\n"
    "        └──────────┘ ◄──────────────────────────────┐\n"
    "              ▲                                       │\n"
    "              │ todas las unidades cerradas           │\n"
    "              │ (Donchian/stop/hard)                  │\n"
    "              │                                       │\n"
    "        ┌─────┴───────────────────────────────────┐  │\n"
    "        │              IN-TRADE                    │  │\n"
    "        │  fills de pyramid detectados             │  │\n"
    "        │  → cancel stops viejos, place nuevos     │──┘\n"
    "        └──────────────────────────────────────────┘",
    code))

S.append(PageBreak())

# ── 8. PIPELINE DE EJECUCIÓN EN VIVO ──────────────────────────────────────────
S.append(Paragraph("8. Pipeline de Ejecución en Vivo", h1))

S.append(Paragraph("Cuando dispara una señal de entrada (cierre de vela t):", h3))
S.append(Paragraph(
    "1. Calcular size, niveles de stop, nivel de hard stop<br/>"
    "2. <b>Pre-check de margen:</b> <code>total_4unit_notional / current_leverage × 1.3 ≤ free_USDT</code> — si no, rechaza<br/>"
    "3. Market BUY de Unit 1 → guarda precio de fill + order ID<br/>"
    "4. Coloca 3 órdenes stop-buy en <code>+0.5N</code>, <code>+1.0N</code>, "
    "<code>+1.5N</code> (reduceOnly=False)<br/>"
    "5. Coloca 2 órdenes stop-sell en <code>-2N</code> y hard stop (reduceOnly=True)<br/>"
    "6. Alerta de Telegram con todos los order IDs y precios de trigger<br/>"
    "7. Persiste al state.json", body))

S.append(Paragraph("En cada iteración 4H subsecuente:", h3))
S.append(Paragraph(
    "1. Reconcilia: fetch <code>position_size</code> de BloFin; compara con lo esperado<br/>"
    "2. Si una orden pyramid fue filleada (detectada por ID faltante en "
    "<code>fetch_open_orders(trigger=True)</code>):<br/>"
    "&nbsp;&nbsp;&nbsp;&nbsp;- Añade unidad al state<br/>"
    "&nbsp;&nbsp;&nbsp;&nbsp;- Cancela el stop 2×ATR viejo, coloca uno nuevo a nivel más alto<br/>"
    "&nbsp;&nbsp;&nbsp;&nbsp;- Cancela el hard stop viejo, coloca uno nuevo (recalculado)<br/>"
    "3. Si la posición = 0 pero el state dice in_trade → registra "
    "<code>auto_recovered_offline_close</code>, resetea state<br/>"
    "4. Verifica salida Donchian: si <code>close &lt; donch_low_10</code> → cancela "
    "todas las órdenes, market sell<br/>"
    "5. Envía Telegram en cualquier evento que cambie el state<br/>"
    "6. Heartbeat diario en la primera iteración de cada día UTC", body))

S.append(Paragraph(
    "<b>Idempotencia:</b> <code>last_bar_time</code> en el state previene "
    "procesamiento duplicado de la misma vela 4H a través de reinicios.", body))

# ── 9. CAPA DE HARDENING ──────────────────────────────────────────────────────
S.append(Paragraph("9. Capa de Hardening", h1))

hard_table = [
    ['Feature', 'Trigger', 'Acción'],
    ['Startup safety check', 'Inicio del servicio', 'Verifica schema del state, conectividad API, reconciliación de posición'],
    ['Auto-recovery', 'Inicio del servicio', 'Coincide state ↔ exchange; registra cierres offline; rechaza inicio en divergencia peligrosa'],
    ['Heartbeat diario', 'Primera iteración de nuevo día UTC', 'Telegram con estado, balance, precio BTC'],
    ['Alerta de reconciliación', 'Cada iteración (solo LIVE)', 'Telegram alerta si position size o order IDs divergen'],
    ['Pre-check de margen', 'Pre-entrada', 'Rechaza entrada si free_USDT < (4unit_notional / leverage × 1.3)'],
    ['Hard stop en exchange', 'Todos los trades', 'Stop-market sell wick-based al -5%, gestionado por exchange'],
    ['ATR stop en exchange', 'Todos los trades', 'Stop-market sell wick-based al -2N, gestionado por exchange'],
    ['Cancel-on-restart', 'Si se detecta divergencia', 'cancel_all_orders() para prevenir huérfanos'],
    ['Auto-restart systemd', 'Cualquier crash', 'Restart=on-failure con delay de 30s'],
]
ht = Table(hard_table, colWidths=[1.6*inch, 1.7*inch, 3.6*inch])
ht.setStyle(TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
    ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
    ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
    ('FONTSIZE',   (0, 0), (-1, -1), 8.5),
    ('GRID',       (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
    ('VALIGN',     (0, 0), (-1, -1), 'TOP'),
    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f5f5f5'), colors.white]),
    ('TOPPADDING',   (0, 0), (-1, -1), 4),
    ('BOTTOMPADDING',(0, 0), (-1, -1), 4),
    ('LEFTPADDING',  (0, 0), (-1, -1), 6),
    ('RIGHTPADDING', (0, 0), (-1, -1), 6),
]))
S.append(ht)

S.append(PageBreak())

# ── 10. LIMITACIONES Y TRABAJO FUTURO ─────────────────────────────────────────
S.append(Paragraph("10. Limitaciones Conocidas y Trabajo Futuro", h1))

S.append(Paragraph("Brechas reconocidas:", h2))
S.append(Paragraph(
    "• No hay modelado de fees/funding en el backtest (impacto estimado -5 a -10pp en 4.4y)<br/>"
    "• No hay modelado de slippage (estimado -2 a -5 bps por trade)<br/>"
    "• Single-asset (solo BTC); multi-asset diversificaría pero el cross-validation "
    "mostró que ETH tenía edge cercano a cero con esta estrategia<br/>"
    "• La reconciliación en modo LIVE es parcialmente ciega a los precios exactos "
    "de fill de pyramid (usa precios de trigger como proxy)<br/>"
    "• El timing del cierre de vela 4H significa que las actualizaciones de stop-loss "
    "tienen un lag de hasta 4h respecto a los fills de pyramid", body))

S.append(Paragraph("Posible trabajo futuro:", h2))
S.append(Paragraph(
    "• Añadir detección de funding rate y saltar entradas cuando funding > 0.05% "
    "(costo alto)<br/>"
    "• Walk-forward optimization en el período Donchian de 20 bars (actualmente "
    "es un parámetro con riesgo)<br/>"
    "• Diversificación ETH/SOL vía sizing de posición independiente (requeriría "
    "rehacer la lógica de sizing)<br/>"
    "• Estrechamiento de trailing stop basado en profit (e.g., breakeven stop "
    "después de +1R) — pero esto perjudicó la performance del backtest cuando se probó",
    body))

# ── 11. CONFIGURACIÓN ACTUAL ──────────────────────────────────────────────────
S.append(Paragraph("11. Resumen de Configuración (estado LIVE actual)", h1))

S.append(Preformatted(
    "DRY_RUN          = False\n"
    "INITIAL_CAPITAL  = 500.0       # USD asignados al bot\n"
    "RISK_PCT         = 0.02\n"
    "HARD_STOP_PCT    = 0.05\n"
    "ATR_STOP_MULT    = 2.0\n"
    "PYRAMID_STEP     = 0.5\n"
    "MAX_UNITS        = 4           # Modo Agresivo\n"
    "MAX_LEVERAGE     = 20\n"
    "\n"
    "SYMBOL              = 'BTC/USDT'\n"
    "BLOFIN_SYMBOL       = 'BTC/USDT:USDT'   # Perpetuo USDT-margined\n"
    "TIMEFRAME           = '4h'\n"
    "DONCHIAN_HIGH       = 20\n"
    "DONCHIAN_LOW        = 10\n"
    "ATR_LEN             = 14\n"
    "EMA_REGIME_LEN      = 200\n"
    "EMA_SLOPE_LOOKBACK  = 20",
    code))

S.append(Spacer(1, 18))
S.append(Paragraph(
    "Bot desplegado en Frankfurt (DigitalOcean droplet, $6/mes), modo LIVE activo. "
    "Datos basados en backtest histórico BTC/USDT (Binance), 4H, "
    "Enero 2022 — Mayo 2026. Rendimientos pasados no garantizan rendimientos futuros.",
    footer))

doc.build(S)
print(f"PDF generado: {OUTPUT}")
