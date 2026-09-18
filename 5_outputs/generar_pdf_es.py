"""Generar PDF en español con el resumen ejecutivo de la estrategia Quattro."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak,
    KeepTogether,
)

OUTPUT = "quattro_comparacion_es.pdf"
CHART  = "quattro_comparacion_es.png"

doc = SimpleDocTemplate(
    OUTPUT, pagesize=letter,
    leftMargin=0.7*inch, rightMargin=0.7*inch,
    topMargin=0.6*inch,  bottomMargin=0.6*inch,
)

styles = getSampleStyleSheet()

# Estilos personalizados
title_style = ParagraphStyle(
    'TitleES', parent=styles['Title'], fontSize=20, textColor=colors.HexColor('#1a1a1a'),
    alignment=TA_CENTER, spaceAfter=4, leading=24
)
subtitle_style = ParagraphStyle(
    'SubtitleES', parent=styles['Normal'], fontSize=11,
    textColor=colors.HexColor('#666666'), alignment=TA_CENTER, spaceAfter=14
)
h2_style = ParagraphStyle(
    'H2', parent=styles['Heading2'], fontSize=14,
    textColor=colors.HexColor('#1a1a1a'), spaceBefore=12, spaceAfter=6
)
h3_cons = ParagraphStyle(
    'H3Cons', parent=styles['Heading3'], fontSize=12,
    textColor=colors.HexColor('#27ae60'), spaceBefore=8, spaceAfter=3
)
h3_mod  = ParagraphStyle(
    'H3Mod', parent=styles['Heading3'], fontSize=12,
    textColor=colors.HexColor('#e67e22'), spaceBefore=8, spaceAfter=3
)
h3_agg  = ParagraphStyle(
    'H3Agg', parent=styles['Heading3'], fontSize=12,
    textColor=colors.HexColor('#c0392b'), spaceBefore=8, spaceAfter=3
)
body = ParagraphStyle(
    'Body', parent=styles['Normal'], fontSize=10,
    alignment=TA_JUSTIFY, leading=13, spaceAfter=6
)
body_small = ParagraphStyle(
    'BodySmall', parent=styles['Normal'], fontSize=9,
    alignment=TA_LEFT, leading=12, spaceAfter=3
)
quote_style = ParagraphStyle(
    'Quote', parent=styles['Normal'], fontSize=10, leftIndent=18,
    textColor=colors.HexColor('#555555'), spaceAfter=6, leading=13
)
footer_style = ParagraphStyle(
    'Footer', parent=styles['Normal'], fontSize=8,
    textColor=colors.HexColor('#888888'), alignment=TA_CENTER
)

story = []

# Título
story.append(Paragraph("Estrategia Quattro", title_style))
story.append(Paragraph("Resumen Ejecutivo — Trading Automatizado de Bitcoin", subtitle_style))
story.append(Spacer(1, 6))

# ¿Qué es?
story.append(Paragraph("¿Qué hace Quattro?", h2_style))
story.append(Paragraph(
    "Quattro es un robot de trading automatizado que opera <b>Bitcoin</b> en BloFin. "
    "Sigue tendencias alcistas, entra cuando el mercado rompe máximos, y "
    "<b>compra más cuando ya está ganando</b> (a esto se le llama <i>'piramidación'</i>, "
    "como subir escalones). Sale cuando la tendencia se rompe.",
    body
))
story.append(Paragraph(
    "El bot está activo <b>24/7</b> en un servidor en Frankfurt. Tú no haces nada — "
    "sólo recibes notificaciones por Telegram cuando hace algo.",
    body
))

# Tabla resumen
story.append(Spacer(1, 10))
story.append(Paragraph("Los 3 modos en una tabla", h2_style))

table_data = [
    ['', 'Conservador', 'Moderado', 'Agresivo'],
    ['Ganancia total (4.5 años)', '+127%', '+296%', '+1,107%'],
    ['Caída máxima de la cuenta', '-15%', '-27%', '-37%'],
    ['$1,839 se vuelve...', '$4,167', '$7,276', '$22,196'],
    ['Operaciones en 4.5 años', '89', '91', '94'],
    ['Sensación al usarlo', 'Tranquilo', 'Emocionante', 'Montaña rusa'],
]

tbl = Table(table_data, colWidths=[2.0*inch, 1.3*inch, 1.3*inch, 1.3*inch])
tbl.setStyle(TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
    ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
    ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
    ('FONTSIZE',   (0, 0), (-1, -1), 10),
    ('ALIGN',      (1, 0), (-1, -1), 'CENTER'),
    ('ALIGN',      (0, 0), (0, -1), 'LEFT'),
    ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
    ('GRID',       (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f5f5f5'), colors.white]),
    # Colores por columna en el encabezado
    ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#27ae60')),
    ('BACKGROUND', (2, 0), (2, 0), colors.HexColor('#e67e22')),
    ('BACKGROUND', (3, 0), (3, 0), colors.HexColor('#c0392b')),
    ('FONTNAME',   (0, 1), (0, -1), 'Helvetica-Bold'),
    ('LEFTPADDING',  (0, 0), (-1, -1), 8),
    ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ('TOPPADDING',   (0, 0), (-1, -1), 7),
    ('BOTTOMPADDING',(0, 0), (-1, -1), 7),
]))
story.append(tbl)

# Gráfico
story.append(Spacer(1, 12))
story.append(Paragraph("Comparación visual", h2_style))
img = Image(CHART, width=7.0*inch, height=5.5*inch, kind='proportional')
story.append(img)

# Página 2 — detalle de cada modo
story.append(PageBreak())
story.append(Paragraph("Detalle de cada modo", h2_style))
story.append(Paragraph(
    "Todos los modos usan la <b>misma señal de entrada y el mismo riesgo (2% por operación).</b> "
    "Sólo cambia cuántas veces el bot puede agregar a una operación ganadora.",
    body
))

# Conservador
story.append(Paragraph("🟢 Modo Conservador — \"Estable\"", h3_cons))
story.append(Paragraph(
    "<i>Una sola posición por operación. Si la operación funciona, no agrega más. "
    "Si pierde, pérdida pequeña.</i>",
    quote_style
))
story.append(Paragraph(
    "<b>Ganancia histórica</b> (4.5 años): <b>+127%</b><br/>"
    "<b>Peor caída de la cuenta</b>: <b>-15%</b><br/>"
    "<b>Inversión final</b> (de $1,839): <b>$4,167</b><br/>"
    "<b>Ideal para</b>: alguien que prefiere ganar menos pero dormir tranquilo.",
    body
))

# Moderado
story.append(Paragraph("🟠 Modo Moderado — \"Balanceado\"", h3_mod))
story.append(Paragraph(
    "<i>Hasta 2 posiciones por operación. Si una operación está ganando bien, "
    "el bot agrega una segunda posición. Doble potencial.</i>",
    quote_style
))
story.append(Paragraph(
    "<b>Ganancia histórica</b>: <b>+296%</b> (más del doble del Conservador)<br/>"
    "<b>Peor caída de la cuenta</b>: <b>-27%</b><br/>"
    "<b>Inversión final</b>: <b>$7,276</b><br/>"
    "<b>Ideal para</b>: el punto medio. Más ganancia, sin caídas exageradas.",
    body
))

# Agresivo
story.append(Paragraph("🔴 Modo Agresivo — \"Compuesto\"", h3_agg))
story.append(Paragraph(
    "<i>Hasta 4 posiciones por operación. Cada vez que la operación gana más, "
    "el bot agrega otra capa. Cuando funciona, funciona EN GRANDE. Cuando falla, duele más.</i>",
    quote_style
))
story.append(Paragraph(
    "<b>Ganancia histórica</b>: <b>+1,107%</b> (10x más que el Conservador)<br/>"
    "<b>Peor caída de la cuenta</b>: <b>-37%</b><br/>"
    "<b>Inversión final</b>: <b>$22,196</b><br/>"
    "<b>Ideal para</b>: alguien con paciencia y estómago. Sabe que va a haber meses malos.",
    body
))

# ¿Cómo elegir?
story.append(Spacer(1, 10))
story.append(Paragraph("¿Cómo elegir el modo correcto?", h2_style))
story.append(Paragraph(
    "<b>Pregúntate:</b> <i>\"Si veo mi cuenta bajar X% durante 6 meses sin parar, "
    "¿sigo confiando en el bot o lo apago?\"</i>",
    body
))
choose_table = [
    ['Si -15% ya te duele', '→', 'Conservador'],
    ['Si aguantas -27% sin tocarlo', '→', 'Moderado'],
    ['Si puedes ver -37% y NO entrar en pánico', '→', 'Agresivo'],
]
ct = Table(choose_table, colWidths=[3.5*inch, 0.5*inch, 2.0*inch])
ct.setStyle(TableStyle([
    ('FONTSIZE',   (0, 0), (-1, -1), 10),
    ('ALIGN',      (1, 0), (1, -1), 'CENTER'),
    ('ALIGN',      (2, 0), (2, -1), 'LEFT'),
    ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
    ('TEXTCOLOR',  (2, 0), (2, 0), colors.HexColor('#27ae60')),
    ('TEXTCOLOR',  (2, 1), (2, 1), colors.HexColor('#e67e22')),
    ('TEXTCOLOR',  (2, 2), (2, 2), colors.HexColor('#c0392b')),
    ('FONTNAME',   (2, 0), (2, -1), 'Helvetica-Bold'),
    ('TOPPADDING',   (0, 0), (-1, -1), 5),
    ('BOTTOMPADDING',(0, 0), (-1, -1), 5),
]))
story.append(ct)

story.append(Spacer(1, 6))
story.append(Paragraph(
    "<b>El error más común no es elegir mal el modo</b> — es elegir el Agresivo y apagarlo "
    "en la peor caída, perdiéndote la recuperación que viene después.",
    body
))

# Lo que NO cambia
story.append(Spacer(1, 8))
story.append(Paragraph("Lo que NO cambia entre modos", h2_style))
not_change = [
    ['Riesgo máximo por operación', '2% (siempre)'],
    ['Pérdida máxima por operación', '5% (siempre)'],
    ['Mercado', 'Bitcoin 4H (siempre)'],
    ['Frecuencia', '~20 operaciones por año'],
    ['Tiempo promedio en una operación', '~1 día'],
]
nct = Table(not_change, colWidths=[3.5*inch, 2.5*inch])
nct.setStyle(TableStyle([
    ('FONTSIZE',   (0, 0), (-1, -1), 10),
    ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
    ('FONTNAME',   (1, 0), (1, -1), 'Helvetica-Bold'),
    ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.HexColor('#f5f5f5'), colors.white]),
    ('TOPPADDING',   (0, 0), (-1, -1), 5),
    ('BOTTOMPADDING',(0, 0), (-1, -1), 5),
    ('LEFTPADDING',  (0, 0), (-1, -1), 8),
    ('RIGHTPADDING', (0, 0), (-1, -1), 8),
]))
story.append(nct)

story.append(Spacer(1, 8))
story.append(Paragraph(
    "Lo único que cambia es <b>cuánto acumula el bot cuando una operación está funcionando.</b>",
    body
))

# Footer
story.append(Spacer(1, 20))
story.append(Paragraph(
    "Bot actualmente configurado en modo <b>Agresivo</b> (4 unidades) con filtro adicional "
    "de tendencia confirmada. Capital asignado: $500 USDT como prueba inicial.",
    body_small
))
story.append(Spacer(1, 10))
story.append(Paragraph(
    "Datos basados en backtest histórico sobre BTC/USDT (Binance), 4H, "
    "Enero 2022 — Mayo 2026. Rendimientos pasados no garantizan rendimientos futuros.",
    footer_style
))

doc.build(story)
print(f"PDF generado: {OUTPUT}")
