"""Build the submission PDF from the human-readable Markdown report (reportlab)."""
import re
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle

root=Path(__file__).resolve().parents[1]/'track_2b'
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='Body',fontName='Helvetica',fontSize=10,leading=14,spaceAfter=7,textColor=colors.HexColor('#24372e')))
styles.add(ParagraphStyle(name='SmallCell',fontName='Helvetica',fontSize=9,leading=12))
styles['Title'].textColor=colors.HexColor('#244d38')
styles['Heading2'].textColor=colors.HexColor('#244d38')
styles['Heading2'].spaceBefore=12
styles['Heading2'].spaceAfter=7

def inline(text):
    return re.sub(r'\*\*(.*?)\*\*',r'<b>\1</b>',escape(text))

story=[];buffer=[];rows=[]
def flush():
    if buffer:
        story.append(Paragraph(inline(' '.join(buffer)),styles['Body']));buffer.clear()
def flush_table():
    if rows:
        content=[[Paragraph(inline(cell),styles['SmallCell']) for cell in row] for row in rows]
        widths=[28*mm,35*mm,105*mm] if len(rows[0])==3 else None
        table=Table(content,colWidths=widths,repeatRows=1,hAlign=TA_LEFT)
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e7eee3')),
            ('VALIGN',(0,0),(-1,-1),'TOP'),('BOX',(0,0),(-1,-1),.5,colors.HexColor('#c6d2c5')),
            ('INNERGRID',(0,0),(-1,-1),.3,colors.HexColor('#c6d2c5')),
            ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
            ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
        story.extend([table,Spacer(1,9)]);rows.clear()

for raw in (root/'technical_report.md').read_text(encoding='utf-8-sig').splitlines():
    line=raw.strip()
    if line.startswith('|'):
        flush()
        if not re.fullmatch(r'[| :\-]+',line):rows.append([c.strip() for c in line.strip('|').split('|')])
        continue
    flush_table()
    if line=='<!-- page -->':flush();story.append(PageBreak())
    elif line.startswith('# '):flush();story.append(Paragraph(inline(line[2:]),styles['Title']))
    elif line.startswith('## '):flush();story.append(Paragraph(inline(line[3:]),styles['Heading2']))
    elif not line:flush()
    else:buffer.append(line)
flush();flush_table()

def footer(canvas,doc):
    canvas.saveState();canvas.setStrokeColor(colors.HexColor('#c6d2c5'))
    canvas.line(21*mm,18*mm,189*mm,18*mm);canvas.setFont('Helvetica',8)
    canvas.setFillColor(colors.HexColor('#607366'))
    canvas.drawString(21*mm,13*mm,'Sovereign Trade Copilot | Human approval required')
    canvas.drawRightString(189*mm,13*mm,f'Page {doc.page}');canvas.restoreState()

out=root/'SovereignTradeCopilot_Report.pdf'
doc=SimpleDocTemplate(str(out),pagesize=(210*mm,297*mm),leftMargin=21*mm,rightMargin=21*mm,
    topMargin=18*mm,bottomMargin=25*mm,title='Sovereign Trade Copilot',author='Sovereign Trade Copilot')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
print(out.name)
