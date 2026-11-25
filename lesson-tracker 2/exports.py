"""Excel and PDF downloads. Chinese text in the PDF uses the bundled Droid font."""
import zipfile
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

FONT = Path(__file__).resolve().parent / 'fonts' / 'DroidSansFallbackFull.ttf'


def aud(cents):
    if cents is None:
        return ''
    sign = '-' if cents < 0 else ''
    cents = abs(int(cents))
    return f'{sign}{cents // 100}.{cents % 100:02d}'


def _column(index):
    name = ''
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def xlsx_bytes(sheets):
    """sheets is a list of (title, rows). Rows are lists of numbers or strings."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as book:
        book.writestr('[Content_Types].xml', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
''' + ''.join(f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(len(sheets))) + '</Types>')
        book.writestr('_rels/.rels', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>''')
        workbook_rels = ''.join(
            f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i+1}.xml"/>'
            for i in range(len(sheets)))
        book.writestr('xl/_rels/workbook.xml.rels', f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{workbook_rels}</Relationships>''')
        sheet_tags = ''.join(f'<sheet name="{escape(title[:31])}" sheetId="{i+1}" r:id="rId{i+1}"/>' for i, (title, _rows) in enumerate(sheets))
        book.writestr('xl/workbook.xml', f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets>{sheet_tags}</sheets></workbook>''')
        for index, (_title, rows) in enumerate(sheets):
            body = []
            for r, row in enumerate(rows, start=1):
                cells = []
                for c, value in enumerate(row):
                    ref = f'{_column(c)}{r}'
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        cells.append(f'<c r="{ref}"><v>{value}</v></c>')
                    else:
                        cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
                body.append(f'<row r="{r}">{"".join(cells)}</row>')
            book.writestr(f'xl/worksheets/sheet{index+1}.xml', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>''' + ''.join(body) + '</sheetData></worksheet>')
    return buffer.getvalue()


def finance_rows(data):
    summary = [
        ['HZ Education Melbourne', data['start'], data['end'], '金额为澳元，不含 GST'],
        ['机构收入', aud(data['turnover_cents'])],
        ['本期实收（另列，不重复计入利润）', aud(data['cash_received_cents'])],
        ['本期实退', aud(data['cash_refunded_cents'])],
        ['老师课酬合计', aud(data['teacher_pay_cents'])],
        ['机构成本', aud((data.get('dashboard') or {}).get('cost_cents', data['operating_cost_cents']))],
        ['毛利率 %', '' if data['gross_margin_percent'] is None else data['gross_margin_percent']],
        ['机构利润', aud(data['organisation_profit_cents'])],
        ['Vincent 分成', aud(data['partner']['share_cents'])],
        ['我的学生收入', aud(data['helen_teaching_cents'])],
        ['本月我的总收入', aud(data['helen_net_cents'])],
        [],
        ['老师', '节数', '小时', '课酬基数', '应付课酬'],
    ]
    for teacher in data['teachers']:
        summary.append([teacher['name'] + ('（Helen）' if teacher['is_helen'] else ''), teacher['lessons'],
            round(teacher['minutes'] / 60, 2), aud(teacher['fee_cents']), aud(teacher['pay_cents'])])
    methods = [['收款方式', '金额']] + [[row['label'], aud(row['cents'])] for row in data['by_method']]
    receivers = [['收款人', '金额', '未上交']] + [[row['name'], aud(row['cents']), aud(row['unhanded_cents'])] for row in data['by_receiver']]
    outstanding = [['日期', '学生', '收款人', '方式', '金额', '备注']]
    for row in data['unhanded']:
        outstanding.append([row['lesson_date'], row['student_name'], row.get('receiver_name') or '',
            row['payment_method'], aud(row['cash_delta']), row.get('reference') or ''])
    cost_rows = (data.get('dashboard') or {}).get('costs') or data['costs']
    costs = [['成本', '金额']] + [[row['label'], aud(row['amount_cents'])] for row in cost_rows]
    return [('汇总', summary), ('收款方式', methods), ('收款人', receivers), ('未上交', outstanding), ('成本', costs)]


def finance_xlsx(data):
    return xlsx_bytes(finance_rows(data))


def finance_pdf(data):
    from fpdf import FPDF
    if not FONT.is_file():
        raise RuntimeError('缺少中文字体，暂时无法导出 PDF。')
    pdf = FPDF(format='A4')
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_font('Droid', '', str(FONT))
    pdf.add_page()
    pdf.set_font('Droid', size=18)
    pdf.cell(0, 12, 'HZ Education Melbourne', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Droid', size=11)
    pdf.cell(0, 8, f"{data['start']} 至 {data['end']}    澳元，不含 GST", new_x='LMARGIN', new_y='NEXT')
    pdf.ln(2)
    lines = [
        ('机构收入', aud(data['turnover_cents'])),
        ('本期实收（另列）', aud(data['cash_received_cents'])),
        ('老师课酬', aud(data['teacher_pay_cents'])),
        ('机构成本', aud((data.get('dashboard') or {}).get('cost_cents', data['operating_cost_cents']))),
        ('毛利率', '' if data['gross_margin_percent'] is None else f"{data['gross_margin_percent']}%"),
        ('机构利润', aud(data['organisation_profit_cents'])),
        ('Vincent 分成', aud(data['partner']['share_cents'])),
        ('我的学生收入', aud(data['helen_teaching_cents'])),
        ('本月我的总收入', aud(data['helen_net_cents'])),
    ]
    for label, value in lines:
        pdf.set_font('Droid', size=12)
        pdf.cell(120, 9, label)
        pdf.cell(0, 9, value, new_x='LMARGIN', new_y='NEXT')
    pdf.ln(4)
    pdf.set_font('Droid', size=14)
    pdf.cell(0, 10, '老师课酬', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Droid', size=11)
    for teacher in data['teachers']:
        name = teacher['name'] + ('（Helen）' if teacher['is_helen'] else '')
        pdf.cell(0, 8, f"{name}    {teacher['lessons']} 节    {aud(teacher['pay_cents'])}", new_x='LMARGIN', new_y='NEXT')
    pdf.ln(3)
    pdf.set_font('Droid', size=14)
    pdf.cell(0, 10, '按收款方式和收款人', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Droid', size=11)
    for row in data['by_method']:
        pdf.cell(0, 8, f"{row['label']}    {aud(row['cents'])}", new_x='LMARGIN', new_y='NEXT')
    for row in data['by_receiver']:
        pdf.cell(0, 8, f"{row['name']}    {aud(row['cents'])}    未上交 {aud(row['unhanded_cents'])}", new_x='LMARGIN', new_y='NEXT')
    if data['unhanded']:
        pdf.ln(3)
        pdf.set_font('Droid', size=14)
        pdf.cell(0, 10, '老师已收、尚未上交', new_x='LMARGIN', new_y='NEXT')
        pdf.set_font('Droid', size=11)
        for row in data['unhanded']:
            pdf.multi_cell(0, 8, f"{row['lesson_date']}  {row['student_name']}  {row.get('receiver_name') or ''}  {aud(row['cash_delta'])}")
    pdf.set_font('Droid', size=9)
    pdf.ln(4)
    pdf.multi_cell(0, 6, '机构利润 = 上课营业额 − 老师课酬 − 运营成本。Helen 净利 = 机构利润 − Vincent 的新学生分成。实收按收款日记，不重复加进利润。')
    return bytes(pdf.output())
