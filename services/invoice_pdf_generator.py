"""
services/invoice_pdf_generator.py - Professional Invoice PDF Generator using ReportLab
"""

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
import io


class InvoicePDFGenerator:
    """Generate professional PDF invoices using ReportLab"""
    
    def __init__(self, invoice_data, company_data):
        self.invoice = invoice_data
        self.company = company_data
        self.buffer = io.BytesIO()
        self.doc = SimpleDocTemplate(
            self.buffer,
            pagesize=A4,
            rightMargin=0.7*cm,
            leftMargin=0.7*cm,
            topMargin=0.7*cm,
            bottomMargin=0.7*cm
        )
        self.styles = getSampleStyleSheet()
        self._setup_styles()
        self.elements = []
    
    def _setup_styles(self):
        # Company Name
        self.styles.add(ParagraphStyle(
            name='CompanyName',
            parent=self.styles['Heading1'],
            fontSize=18,
            textColor=colors.HexColor('#16A34A'),
            alignment=TA_LEFT,
            spaceAfter=2,
            fontName='Helvetica-Bold'
        ))
        
        # Company Subtitle
        self.styles.add(ParagraphStyle(
            name='CompanySub',
            parent=self.styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#4B5563'),
            alignment=TA_LEFT,
            spaceAfter=1,
            fontName='Helvetica'
        ))
        
        # Invoice Title
        self.styles.add(ParagraphStyle(
            name='InvoiceTitle',
            parent=self.styles['Heading2'],
            fontSize=16,
            textColor=colors.HexColor('#1F2937'),
            alignment=TA_RIGHT,
            spaceAfter=4,
            fontName='Helvetica-Bold'
        ))
        
        # AWB Number
        self.styles.add(ParagraphStyle(
            name='AWBNumber',
            parent=self.styles['Normal'],
            fontSize=20,
            textColor=colors.HexColor('#16A34A'),
            alignment=TA_CENTER,
            spaceAfter=4,
            fontName='Helvetica-Bold'
        ))
        
        # Meta Label
        self.styles.add(ParagraphStyle(
            name='MetaLabel',
            parent=self.styles['Normal'],
            fontSize=7,
            textColor=colors.HexColor('#6B7280'),
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))
        
        # Meta Value
        self.styles.add(ParagraphStyle(
            name='MetaValue',
            parent=self.styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#111827'),
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))
        
        # Party Label
        self.styles.add(ParagraphStyle(
            name='PartyLabel',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#6B7280'),
            alignment=TA_LEFT,
            fontName='Helvetica-Bold'
        ))
        
        # Party Name
        self.styles.add(ParagraphStyle(
            name='PartyName',
            parent=self.styles['Normal'],
            fontSize=12,
            textColor=colors.HexColor('#111827'),
            alignment=TA_LEFT,
            fontName='Helvetica-Bold'
        ))
        
        # Party Address
        self.styles.add(ParagraphStyle(
            name='PartyAddr',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#4B5563'),
            alignment=TA_LEFT,
            fontName='Helvetica'
        ))
        
        # Table Header
        self.styles.add(ParagraphStyle(
            name='TableHeader',
            parent=self.styles['Normal'],
            fontSize=9,
            textColor=colors.white,
            alignment=TA_LEFT,
            fontName='Helvetica-Bold'
        ))
        
        # Table Cell
        self.styles.add(ParagraphStyle(
            name='TableCell',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#111827'),
            alignment=TA_LEFT,
            fontName='Helvetica'
        ))
        
        # Total Amount
        self.styles.add(ParagraphStyle(
            name='TotalAmount',
            parent=self.styles['Normal'],
            fontSize=14,
            textColor=colors.white,
            alignment=TA_RIGHT,
            fontName='Helvetica-Bold'
        ))

    def _add_header(self):
        company_name = self.company.company_name if self.company else "Nexa Logistics"
        invoice_id = self.invoice.get('invoice_id', '')
        invoice_date = self.invoice.get('date', '')
        docket_no = self.invoice.get('docket_no', '')
        
        left_text = [
            Paragraph(company_name, self.styles['CompanyName']),
            Paragraph("INTERNATIONAL COURIER | FREIGHT FORWARDER", self.styles['CompanySub']),
            Paragraph(f"Website: www.{company_name.replace(' ', '').lower()}.net | E-mail: info@{company_name.replace(' ', '').lower()}.net", self.styles['CompanySub']),
        ]
        
        right_text = [
            Paragraph("CUSTOMER INVOICE", self.styles['InvoiceTitle']),
            Paragraph(invoice_id, self.styles['InvoiceTitle']),
            Paragraph(f"Date: {invoice_date.strftime('%d %b %Y') if invoice_date else '—'}", self.styles['MetaValue']),
            Paragraph(f"AWB: {docket_no}", self.styles['AWBNumber']),
        ]
        
        data = [
            [Paragraph('<br/>'.join([str(x) for x in left_text]), self.styles['Normal']),
             Paragraph('<br/>'.join([str(x) for x in right_text]), self.styles['Normal'])]
        ]
        
        header_table = Table(data, colWidths=[11*cm, 8*cm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
        ]))
        self.elements.append(header_table)
        self.elements.append(Spacer(1, 0.2*cm))
        self.elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#16A34A')))
        self.elements.append(Spacer(1, 0.2*cm))

    def _add_awb_barcode(self, awb):
        self.elements.append(Paragraph(awb, self.styles['AWBNumber']))
        self.elements.append(Spacer(1, 0.1*cm))
        
        barcode = ""
        for i in range(80):
            width = 1 if i % 3 == 0 else 2
            barcode += '█' * width
        self.elements.append(Paragraph(barcode, self.styles['Normal']))
        self.elements.append(Spacer(1, 0.1*cm))
        self.elements.append(Paragraph(awb, self.styles['AWBNumber']))
        self.elements.append(Spacer(1, 0.2*cm))

    def _add_meta_row(self, meta, customer_name, packages):
        total_weight = sum((p.get('weight') or 0) * (p.get('qty') or 1) for p in packages)
        
        meta_items = [
            ('ACCOUNT / INVOICE NO.', self.invoice.get('invoice_id', '')),
            ('CUSTOMER', meta.get('shipper_name', '') or customer_name),
            ('ORIGIN', meta.get('origin', 'India')),
            ('DESTINATION', meta.get('destination', '')),
            ('SERVICE', f"WT: {total_weight:.2f} kg"),
        ]
        
        flat = []
        for label, value in meta_items:
            flat.append(Paragraph(label, self.styles['MetaLabel']))
            flat.append(Paragraph(str(value) if value else '—', self.styles['MetaValue']))
        
        meta_table = Table([flat], colWidths=[2.5*cm, 1.8*cm, 2.5*cm, 1.8*cm, 2.5*cm, 1.8*cm])
        meta_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F9FAFB')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        self.elements.append(meta_table)
        self.elements.append(Spacer(1, 0.2*cm))

    def _add_parties(self, meta, customer_name, customer_phone):
        shipper_addr = meta.get('shipper_address1', '')
        if meta.get('shipper_address2'):
            shipper_addr += ', ' + meta.get('shipper_address2')
        if meta.get('shipper_city'):
            shipper_addr += ', ' + meta.get('shipper_city')
        if meta.get('shipper_state'):
            shipper_addr += ', ' + meta.get('shipper_state')
        if meta.get('shipper_pincode'):
            shipper_addr += ' - ' + meta.get('shipper_pincode')
        
        receiver_addr = meta.get('receiver_address1', '')
        if meta.get('receiver_address2'):
            receiver_addr += ', ' + meta.get('receiver_address2')
        if meta.get('receiver_city'):
            receiver_addr += ', ' + meta.get('receiver_city')
        if meta.get('receiver_state'):
            receiver_addr += ', ' + meta.get('receiver_state')
        if meta.get('receiver_pincode'):
            receiver_addr += ' - ' + meta.get('receiver_pincode')
        
        shipper_text = f"""
        <b>SENDER'S NAME</b><br/>{meta.get('shipper_name', '') or customer_name or '—'}<br/><br/>
        <b>ADDRESS</b><br/>{shipper_addr or '—'}<br/><br/>
        <b>PHONE:</b> {customer_phone or '—'}
        """
        
        receiver_text = f"""
        <b>RECIPIENT'S NAME</b><br/>{meta.get('receiver_name', '—')}<br/><br/>
        <b>ADDRESS</b><br/>{receiver_addr or '—'}<br/><br/>
        <b>PHONE:</b> {meta.get('receiver_phone', '—')}
        """
        
        party_data = [
            [Paragraph(shipper_text, self.styles['Normal']),
             Paragraph(receiver_text, self.styles['Normal'])]
        ]
        
        party_table = Table(party_data, colWidths=[9.5*cm, 9.5*cm])
        party_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
            ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#F9FAFB')),
            ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#F9FAFB')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ]))
        self.elements.append(party_table)
        self.elements.append(Spacer(1, 0.2*cm))

    def _add_items_table(self, items, meta, subtotal):
        table_data = [
            [Paragraph('#', self.styles['TableHeader']),
             Paragraph('Description', self.styles['TableHeader']),
             Paragraph('Qty', self.styles['TableHeader']),
             Paragraph('Rate (₹)', self.styles['TableHeader']),
             Paragraph('Amount (₹)', self.styles['TableHeader'])]
        ]
        
        for idx, item in enumerate(items, 1):
            table_data.append([
                Paragraph(str(idx), self.styles['TableCell']),
                Paragraph(item.get('desc', '—')[:40], self.styles['TableCell']),
                Paragraph(str(item.get('qty', 0)), self.styles['TableCell']),
                Paragraph(f"{item.get('rate', 0):.2f}", self.styles['TableCell']),
                Paragraph(f"{item.get('amount', 0):.2f}", self.styles['TableCell'])
            ])
        
        # Freight
        freight = meta.get('freight', subtotal)
        freight_weight = meta.get('freight_weight', 0)
        freight_rate = meta.get('freight_rate_per_kg', 0)
        if freight > 0:
            table_data.append([
                Paragraph('', self.styles['TableCell']),
                Paragraph(f"Freight ({freight_weight} kg × {freight_rate}/kg)", self.styles['TableCell']),
                Paragraph('', self.styles['TableCell']),
                Paragraph('', self.styles['TableCell']),
                Paragraph(f"{freight:.2f}", self.styles['TableCell'])
            ])
        
        # Fuel
        fuel = meta.get('fuel', 0)
        if fuel > 0:
            table_data.append([
                Paragraph('', self.styles['TableCell']),
                Paragraph("Fuel Surcharge", self.styles['TableCell']),
                Paragraph('', self.styles['TableCell']),
                Paragraph('', self.styles['TableCell']),
                Paragraph(f"{fuel:.2f}", self.styles['TableCell'])
            ])
        
        # Other charges
        other = meta.get('other', 0)
        if other > 0:
            table_data.append([
                Paragraph('', self.styles['TableCell']),
                Paragraph("Other Charges", self.styles['TableCell']),
                Paragraph('', self.styles['TableCell']),
                Paragraph('', self.styles['TableCell']),
                Paragraph(f"{other:.2f}", self.styles['TableCell'])
            ])
        
        # Subtotal
        table_data.append([
            Paragraph('', self.styles['TableCell']),
            Paragraph('', self.styles['TableCell']),
            Paragraph('', self.styles['TableCell']),
            Paragraph('Subtotal', self.styles['TableCell']),
            Paragraph(f"{subtotal:.2f}", self.styles['TableCell'])
        ])
        
        # GST
        tax = self.invoice.get('tax', 0)
        if tax > 0:
            table_data.append([
                Paragraph('', self.styles['TableCell']),
                Paragraph('', self.styles['TableCell']),
                Paragraph('', self.styles['TableCell']),
                Paragraph('GST (18%)', self.styles['TableCell']),
                Paragraph(f"{tax:.2f}", self.styles['TableCell'])
            ])
        
        # Grand Total
        total = self.invoice.get('total', 0)
        table_data.append([
            Paragraph('', self.styles['TableCell']),
            Paragraph('', self.styles['TableCell']),
            Paragraph('', self.styles['TableCell']),
            Paragraph('GRAND TOTAL', self.styles['TableHeader']),
            Paragraph(f"{total:.2f}", self.styles['TotalAmount'])
        ])
        
        item_table = Table(table_data, colWidths=[0.8*cm, 8.5*cm, 1.2*cm, 2.2*cm, 2.5*cm])
        
        style = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#16A34A')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('GRID', (0, 0), (-1, -2), 0.5, colors.HexColor('#E5E7EB')),
            ('FONTSIZE', (0, 1), (-1, -2), 8),
            ('ALIGN', (2, 1), (2, -2), 'CENTER'),
            ('ALIGN', (3, 1), (-1, -2), 'RIGHT'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#16A34A')),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.white),
            ('FONTSIZE', (0, -1), (-1, -1), 11),
            ('TOPPADDING', (0, -1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, -1), (-1, -1), 8),
        ]
        item_table.setStyle(TableStyle(style))
        self.elements.append(item_table)
        self.elements.append(Spacer(1, 0.2*cm))

    def _add_payment_summary(self):
        paid = self.invoice.get('paid', 0)
        balance = self.invoice.get('balance', 0)
        
        summary_data = [
            ['Amount Paid', f"₹{paid:.2f}"],
            ['Balance Due', f"₹{balance:.2f}"]
        ]
        
        summary_table = Table(summary_data, colWidths=[4*cm, 3*cm])
        summary_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (1, 0), (1, 0), colors.HexColor('#16A34A')),
            ('TEXTCOLOR', (1, 1), (1, 1), colors.HexColor('#DC2626')),
            ('FONTNAME', (1, 1), (1, 1), 'Helvetica-Bold'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        
        wrapper = Table([[summary_table]], colWidths=[19*cm])
        wrapper.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ]))
        self.elements.append(wrapper)
        self.elements.append(Spacer(1, 0.2*cm))

    def _add_packages(self, packages):
        if not packages:
            return
        
        self.elements.append(Paragraph("📦 Packages", self.styles['PartyLabel']))
        self.elements.append(Spacer(1, 0.1*cm))
        
        pkg_data = [
            [Paragraph('#', self.styles['TableHeader']),
             Paragraph('Item', self.styles['TableHeader']),
             Paragraph('Type', self.styles['TableHeader']),
             Paragraph('Qty', self.styles['TableHeader']),
             Paragraph('Weight', self.styles['TableHeader'])]
        ]
        
        for idx, pkg in enumerate(packages, 1):
            pkg_data.append([
                Paragraph(str(idx), self.styles['TableCell']),
                Paragraph(pkg.get('name', '—'), self.styles['TableCell']),
                Paragraph(pkg.get('type', '—'), self.styles['TableCell']),
                Paragraph(str(pkg.get('qty', 1)), self.styles['TableCell']),
                Paragraph(f"{pkg.get('weight', 0)} kg", self.styles['TableCell'])
            ])
        
        pkg_table = Table(pkg_data, colWidths=[0.8*cm, 6*cm, 3*cm, 1.5*cm, 2.5*cm])
        pkg_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#374151')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (3, 1), (3, -1), 'CENTER'),
            ('ALIGN', (4, 1), (4, -1), 'CENTER'),
        ]))
        self.elements.append(pkg_table)
        self.elements.append(Spacer(1, 0.2*cm))

    def _add_performa_items(self, performa_items):
        if not performa_items:
            return
        
        self.elements.append(Paragraph("📋 Performa Invoice Items", self.styles['PartyLabel']))
        self.elements.append(Spacer(1, 0.1*cm))
        
        perf_data = [
            [Paragraph('#', self.styles['TableHeader']),
             Paragraph('Description', self.styles['TableHeader']),
             Paragraph('Qty', self.styles['TableHeader']),
             Paragraph('Rate (₹)', self.styles['TableHeader']),
             Paragraph('Amount (₹)', self.styles['TableHeader'])]
        ]
        
        perf_total = 0
        for idx, item in enumerate(performa_items, 1):
            amt = item.get('qty', 0) * item.get('rate', 0)
            perf_total += amt
            perf_data.append([
                Paragraph(str(idx), self.styles['TableCell']),
                Paragraph(item.get('description', '—')[:40], self.styles['TableCell']),
                Paragraph(str(item.get('qty', 0)), self.styles['TableCell']),
                Paragraph(f"{item.get('rate', 0):.2f}", self.styles['TableCell']),
                Paragraph(f"{amt:.2f}", self.styles['TableCell'])
            ])
        
        perf_data.append([
            Paragraph('', self.styles['TableCell']),
            Paragraph('', self.styles['TableCell']),
            Paragraph('', self.styles['TableCell']),
            Paragraph('TOTAL', self.styles['TableHeader']),
            Paragraph(f"{perf_total:.2f}", self.styles['TotalAmount'])
        ])
        
        perf_table = Table(perf_data, colWidths=[0.8*cm, 8.5*cm, 1.2*cm, 2.2*cm, 2.5*cm])
        perf_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F46E5')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (2, 1), (2, -1), 'CENTER'),
            ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#4F46E5')),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.white),
            ('FONTSIZE', (0, -1), (-1, -1), 11),
            ('TOPPADDING', (0, -1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, -1), (-1, -1), 8),
        ]))
        self.elements.append(perf_table)
        self.elements.append(Spacer(1, 0.2*cm))

    def _add_footer(self, meta):
        payment_mode = meta.get('payment_mode', 'Cash')
        cheque_no = meta.get('cheque_no', '')
        upi_app = meta.get('upi_app', '')
        
        footer_text = f"Payment Mode: {payment_mode.capitalize()}"
        if upi_app:
            footer_text += f" via {upi_app}"
        if cheque_no:
            footer_text += f" • Cheque: {cheque_no}"
        
        footer_data = [
            [Paragraph(footer_text, self.styles['MetaValue']),
             Paragraph('Authorised Signatory', self.styles['MetaValue'])]
        ]
        
        footer_table = Table(footer_data, colWidths=[12*cm, 7*cm])
        footer_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('TOPPADDING', (0, 0), (-1, -1), 30),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
        ]))
        self.elements.append(footer_table)
        
        terms = """
        <font size="7" color="#6B7280">
        <b>Terms & Conditions:</b><br/>
        1. No Claims would be entertained for any damage during transit &amp; delay in delivery due to any reason. | 
        2. Maximum claims for loss of parcel would be USD 50 upto 10 Kgs &amp; USD 100 above 10 kgs or the declared value whichever is lower. | 
        3. This AWB is for the account holder and it is not transferable.
        </font>
        """
        self.elements.append(Paragraph(terms, self.styles['Normal']))

    def generate(self):
        """Generate the PDF"""
        meta = self.invoice.get('meta', {})
        packages = self.invoice.get('packages', [])
        performa_items = self.invoice.get('performa_items', [])
        customer_name = self.invoice.get('customer_name', '')
        customer_phone = self.invoice.get('customer_phone', '')
        subtotal = self.invoice.get('subtotal', 0)
        items = self.invoice.get('items', [])
        
        self._add_header()
        self._add_awb_barcode(self.invoice.get('docket_no', ''))
        self._add_meta_row(meta, customer_name, packages)
        self._add_parties(meta, customer_name, customer_phone)
        self._add_items_table(items, meta, subtotal)
        self._add_payment_summary()
        self._add_packages(packages)
        self._add_performa_items(performa_items)
        self._add_footer(meta)
        
        # Build the PDF
        self.doc.build(self.elements)
        self.buffer.seek(0)
        return self.buffer.getvalue()


def generate_invoice_pdf(invoice_data, company_data):
    """Generate invoice PDF from data"""
    generator = InvoicePDFGenerator(invoice_data, company_data)
    return generator.generate()