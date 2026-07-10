# tasks.py - UPDATED with app context

import threading
import time
import json
from datetime import datetime
import os 

# Import app at the top
from app import app, generate_pdf_token  # Assuming your Flask app is in app.py

def _run_invoice_notification(company_id, invoice_id, event="generate", max_retries=2):
    """Run inside the Flask application context"""
    # ─── CRITICAL: Push app context ──────────────────────────────────────────
    with app.app_context():
        from platform_models import Company
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
            to_phone = (client.phone if client else None) or invoice.phone
            
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

            base_url = os.environ.get("BASE_URL", "https://impulse-sanding-handwash.ngrok-free.dev")
            pdf_token = generate_pdf_token(company_id, invoice_id)
            pdf_url = f"{base_url}/invoice/pdf/{invoice_id}?token={pdf_token}"
            
            if event == "update":
                template_name = company.whatsapp_template_update or "shipment_update"
                template_key = "invoice_updated"
            else:
                template_name = company.whatsapp_template_generate or "booking_confirmation"
                template_key = "invoice_created"

            print(f"[WhatsApp] template_name: {template_name}")
            print(f"[WhatsApp] to_phone: {to_phone}")

            params = [
                docket_no,
                invoice.date.strftime("%d-%b-%Y"),
                company.phone or "",
            ]
            
            fallback_message = (
                f"Your shipment {docket_no} is booked on {invoice.date.strftime('%d-%b-%Y')}. "
                f"Contact {company.phone or ''}"
            )

            attempt = 0
            result = None
            while attempt <= max_retries:
                result = send_or_manual(
                    company=company,
                    to_number=to_phone,
                    template_name=template_name,
                    params=params,
                    fallback_message=fallback_message,
                    media_url=pdf_url,
                )
                if result.get("sent") or result.get("manual_link"):
                    break
                attempt += 1
                if attempt <= max_retries:
                    time.sleep(5 * attempt)

            # Log the result
            log = WhatsAppLog(
                company_id=company_id,
                template_key=template_key,
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
                print(f"[whatsapp] ✅ Invoice {invoice_id} notification sent successfully")
            elif result.get("manual_link"):
                print(f"[whatsapp] 🔗 Invoice {invoice_id}: Manual link: {result.get('manual_link')}")
            else:
                print(f"[whatsapp] ❌ Invoice {invoice_id} failed: {result.get('error')}")

        except Exception as e:
            print(f"[whatsapp] ❌ Error: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            close_customer_session(company_id)


def send_invoice_generate_notification_async(company_id, invoice_id):
    """Fire-and-forget with app context"""
    t = threading.Thread(
        target=_run_invoice_notification,
        args=(company_id, invoice_id, "generate"),
        daemon=True,
    )
    t.start()


def send_invoice_update_notification_async(company_id, invoice_id):
    """Fire-and-forget with app context"""
    t = threading.Thread(
        target=_run_invoice_notification,
        args=(company_id, invoice_id, "update"),
        daemon=True,
    )
    t.start()

def _run_carrier_update_notification(company_id, invoice_id, carrier, carrier_ref, max_retries=2):
    with app.app_context():
        from platform_models import Company
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
            to_phone = (client.phone if client else None) or invoice.phone
            client_name = client.name if client else ""

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
            docket_no = meta.get("docket_no", invoice.invoice_id)
            meta = {}
            if invoice.terms:
                try:
                    meta = json.loads(invoice.terms)
                except Exception:
                    pass
            docket_no = meta.get("docket_no", invoice.invoice_id)
            destination = meta.get("destination", "")
            expected_delivery = meta.get("expected_delivery", "")
            template_name = company.whatsapp_template_carrier_update or "carrier_reference_update"
            params = [client_name or "Customer", docket_no, carrier_ref, carrier or "", destination, expected_delivery]
            fallback_message = (
                f"Dear {client_name or 'Customer'},\n"
                f"Your shipment {docket_no} has been updated with carrier reference: {carrier_ref}\n"
                f"Carrier: {carrier or ''}\n"
                f"Please use this reference to track your shipment.\n"
                f"Thank you for choosing us."
            )

            attempt = 0
            result = None
            while attempt <= max_retries:
                result = send_or_manual(
                    company=company, to_number=to_phone, template_name=template_name,
                    params=params, fallback_message=fallback_message,
                )
                if result.get("sent") or result.get("manual_link"):
                    break
                attempt += 1
                if attempt <= max_retries:
                    time.sleep(5 * attempt)

            cdb.add(WhatsAppLog(
                company_id=company_id, template_key="carrier_ref_updated", to_phone=to_phone,
                invoice_id=invoice.invoice_id,
                status="sent" if result.get("sent") else ("manual_pending" if result.get("manual_link") else "failed"),
                provider=company.whatsapp_provider, provider_msg_id=result.get("message_id"),
                error_message=result.get("error"), manual_link=result.get("manual_link"),
                attempt_count=attempt + 1, sent_at=datetime.utcnow() if result.get("sent") else None,
            ))
            cdb.commit()
        finally:
            close_customer_session(company_id)


def send_carrier_update_notification_async(company_id, invoice_id, carrier, carrier_ref):
    t = threading.Thread(
        target=_run_carrier_update_notification,
        args=(company_id, invoice_id, carrier, carrier_ref),
        daemon=True,
    )
    t.start()