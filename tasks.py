# tasks.py - SIMPLIFIED: fixed template registry, no dynamic DB variable mapping

import threading
import time
import json
from datetime import datetime
import os

from app import app, generate_pdf_token


def _run_invoice_notification(company_id, invoice_id, event="generate", max_retries=2):
    """Run inside the Flask application context"""
    with app.app_context():
        from platform_models import Company, WhatsAppTemplate
        from customer_models import Client, Invoice, WhatsAppLog
        from db_router import get_customer_session, close_customer_session
        from whatsapp_service import send_or_manual

        cdb = get_customer_session(company_id)
        try:
            company = Company.query.filter_by(company_id=company_id).first()

            print(f"[WhatsApp] ========== START ==========")
            print(f"[WhatsApp] company_id: {company_id}")
            print(f"[WhatsApp] invoice_id: {invoice_id}")
            print(f"[WhatsApp] event: {event}")

            if not company or not company.whatsapp_api_key:
                print(f"[whatsapp] Company {company_id} has no WhatsApp API key configured")
                return

            invoice = cdb.query(Invoice).filter_by(invoice_id=invoice_id, company_id=company_id).first()
            if not invoice:
                print(f"[whatsapp] Invoice {invoice_id} not found")
                return

            client = cdb.query(Client).filter_by(id=invoice.client_id).first()
            to_phone = invoice.phone or (client.phone if client else None)

            if to_phone:
                to_phone = ''.join(filter(str.isdigit, to_phone))
                if len(to_phone) == 10:
                    to_phone = "91" + to_phone

            if not to_phone:
                print(f"[whatsapp] No phone number found for invoice {invoice_id}")
                return

            meta = {}
            if invoice.terms:
                try:
                    meta = json.loads(invoice.terms)
                except Exception:
                    pass
            docket_no = meta.get("docket_no", invoice.invoice_id)

            event_key = "invoice_updated" if event == "update" else "invoice_created"

            # Template name is admin-set per company/event in WhatsApp
            # Settings (WhatsAppTemplate row). The variable list itself is
            # fixed in code, not stored — [receiver_name, docket_no, date,
            # phone] — so a row saved under an older UI version can't send
            # stale/mismatched params here.
            tpl = WhatsAppTemplate.query.filter_by(
                company_id=company_id, template_key=event_key, is_active=True
            ).first()

            if not tpl or not tpl.template_name:
                reason = (
                    f"No WhatsApp template name configured for company '{company_id}', "
                    f"event '{event_key}'. Go to WhatsApp Settings and set a "
                    f"template name before sending."
                )
                print(f"[whatsapp] \u274c REJECTED (config error): {reason}")
                cdb.add(WhatsAppLog(
                    company_id=company_id,
                    template_key=event_key,
                    to_phone=to_phone,
                    invoice_id=invoice.invoice_id,
                    status="failed",
                    provider=company.whatsapp_provider,
                    error_message=reason,
                    attempt_count=0,
                ))
                cdb.commit()
                return

            template_name = tpl.template_name
            params = [
                meta.get("receiver_name") or meta.get("receiver_company") or (client.name if client else None) or "Customer",   # receiver_name
                docket_no,                                          # docket_no
                invoice.date.strftime("%d-%b-%Y") if invoice.date else "",  # date
                company.phone or "",                                # phone
            ]

            print(f"[WhatsApp] template_name: {template_name}")
            print(f"[WhatsApp] params ({len(params)}): {params}")
            print(f"[WhatsApp] to_phone: {to_phone}")

            fallback_message = (
                f"Your shipment {docket_no} is booked on {invoice.date.strftime('%d-%b-%Y')}. "
                f"Contact {company.phone or ''}"
            )

            # No PDF auto-attached at booking time — header_type stays "none"
            # unless you explicitly build a separate "share PDF" action later.
            attempt = 0
            result = None
            while attempt <= max_retries:
                result = send_or_manual(
                    company=company,
                    to_number=to_phone,
                    template_name=template_name,
                    params=params,
                    fallback_message=fallback_message,
                    header_type="none",
                )
                if result.get("sent") or result.get("manual_link"):
                    break
                attempt += 1
                if attempt <= max_retries:
                    time.sleep(5 * attempt)

            log = WhatsAppLog(
                company_id=company_id,
                template_key=event_key,
                to_phone=to_phone,
                invoice_id=invoice.invoice_id,
                status="sent" if result.get("sent") else ("manual_pending" if result.get("manual_link") else "failed"),
                provider=company.whatsapp_provider,
                provider_msg_id=result.get("message_id"),
                error_message=result.get("error"),
                manual_link=result.get("manual_link"),
                attempt_count=attempt + 1,
                sent_at=datetime.utcnow() if result.get("sent") else None,
            )
            cdb.add(log)
            cdb.commit()

            if result.get("sent"):
                print(f"[whatsapp] \u2705 Invoice {invoice_id} notification sent successfully")
            elif result.get("manual_link"):
                print(f"[whatsapp] \U0001f517 Invoice {invoice_id}: Manual link: {result.get('manual_link')}")
            else:
                print(f"[whatsapp] \u274c Invoice {invoice_id} failed: {result.get('error')}")

        except Exception as e:
            print(f"[whatsapp] \u274c Error: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            close_customer_session(company_id)


def send_invoice_generate_notification_async(company_id, invoice_id):
    t = threading.Thread(
        target=_run_invoice_notification,
        args=(company_id, invoice_id, "generate"),
        daemon=True,
    )
    t.start()


def send_invoice_update_notification_async(company_id, invoice_id):
    t = threading.Thread(
        target=_run_invoice_notification,
        args=(company_id, invoice_id, "update"),
        daemon=True,
    )
    t.start()


def _run_tracking_update_notification(company_id, invoice_id, carrier, tracking_number, max_retries=2):
    with app.app_context():
        from platform_models import Company, WhatsAppTemplate
        from customer_models import Client, Invoice, WhatsAppLog
        from db_router import get_customer_session, close_customer_session
        from whatsapp_service import send_or_manual

        cdb = get_customer_session(company_id)
        try:
            company = Company.query.filter_by(company_id=company_id).first()
            if not company or not company.whatsapp_api_key:
                return

            invoice = cdb.query(Invoice).filter_by(invoice_id=invoice_id, company_id=company_id).first()
            if not invoice:
                return

            client = cdb.query(Client).filter_by(id=invoice.client_id).first()
            to_phone = invoice.phone or (client.phone if client else None)
            if to_phone:
                to_phone = ''.join(filter(str.isdigit, to_phone))
                if len(to_phone) == 10:
                    to_phone = "91" + to_phone
            if not to_phone:
                return

            meta = {}
            if invoice.terms:
                try:
                    meta = json.loads(invoice.terms)
                except Exception:
                    pass

            event_key = "tracking_number_updated"
            tpl = WhatsAppTemplate.query.filter_by(
                company_id=company_id, template_key=event_key, is_active=True
            ).first()

            if not tpl or not tpl.template_name:
                reason = (
                    f"No WhatsApp template name configured for company '{company_id}', "
                    f"event '{event_key}'. Go to WhatsApp Settings and set a "
                    f"template name before sending."
                )
                cdb.add(WhatsAppLog(
                    company_id=company_id, template_key=event_key, to_phone=to_phone,
                    invoice_id=invoice.invoice_id, status="failed",
                    provider=company.whatsapp_provider, error_message=reason, attempt_count=0,
                ))
                cdb.commit()
                return

            template_name = tpl.template_name
            docket_no = meta.get("docket_no", invoice.invoice_id)
            client_name = (
                meta.get("receiver_name")
                or meta.get("receiver_company")
                or (client.name if client else None)
                or "Customer"
            )

            # Matches the approved template body:
            # "Dear {{1}}, Your shipment {{2}} has been updated with
            #  Tracking Number: {{3}} Carrier: {{4}} Destination: {{5}}
            #  Expected Delivery: {{6}} ..."
            params = [
                client_name,                      # {{1}} receiver_name
                docket_no,                         # {{2}} docket/AWB
                tracking_number or "",             # {{3}} tracking number
                carrier or "",                     # {{4}} carrier
                meta.get("destination", ""),       # {{5}} destination
                meta.get("expected_delivery", ""), # {{6}} expected delivery
            ]

            fallback_message = (
                f"Dear {client_name},\n"
                f"Your shipment {docket_no} has been updated with\n"
                f"Tracking Number: {tracking_number}\n"
                f"Carrier: {carrier or ''}\n"
                f"Destination: {meta.get('destination', '')}\n"
                f"Expected Delivery: {meta.get('expected_delivery', '')}\n\n"
                f"Please use this reference to track your shipment.\n\n"
                f"Thank you for choosing AL Hammad Travels & Courier"
            )

            attempt = 0
            result = None
            while attempt <= max_retries:
                result = send_or_manual(
                    company=company, to_number=to_phone, template_name=template_name,
                    params=params, fallback_message=fallback_message, header_type="none",
                )
                if result.get("sent") or result.get("manual_link"):
                    break
                attempt += 1
                if attempt <= max_retries:
                    time.sleep(5 * attempt)

            cdb.add(WhatsAppLog(
                company_id=company_id, template_key=event_key, to_phone=to_phone,
                invoice_id=invoice.invoice_id,
                status="sent" if result.get("sent") else ("manual_pending" if result.get("manual_link") else "failed"),
                provider=company.whatsapp_provider, provider_msg_id=result.get("message_id"),
                error_message=result.get("error"), manual_link=result.get("manual_link"),
                attempt_count=attempt + 1, sent_at=datetime.utcnow() if result.get("sent") else None,
            ))
            cdb.commit()
        finally:
            close_customer_session(company_id)


def send_tracking_update_notification_async(company_id, invoice_id, carrier, tracking_number):
    t = threading.Thread(
        target=_run_tracking_update_notification,
        args=(company_id, invoice_id, carrier, tracking_number),
        daemon=True,
    )
    t.start()
