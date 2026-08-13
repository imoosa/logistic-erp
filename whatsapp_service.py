"""
whatsapp_service.py - WhatsApp Integration with PDF Attachment Support

UPDATED: header/media block is now gated on an explicit header_type
('document' | 'image' | 'video'), not just "was a media_url passed in."
Previously any call that happened to include a media_url got a header
component injected regardless of whether the company's Meta-approved
template actually had a header slot — that mismatch is what was causing
sends to fail silently for templates that were approved body-only.
"""

import os
import requests
import json
from datetime import datetime

# ─── ENCRYPTION FOR API KEYS ──────────────────────────────────────────────────
try:
    from cryptography.fernet import Fernet
    _KEY = os.environ.get("WHATSAPP_ENCRYPTION_KEY")
    _fernet = Fernet(_KEY.encode()) if _KEY else None
except ImportError:
    _fernet = None


def encrypt_secret(plain: str) -> str:
    if not plain:
        return plain
    if _fernet:
        return _fernet.encrypt(plain.encode()).decode()
    return plain


def decrypt_secret(stored: str) -> str:
    if not stored:
        return stored
    if _fernet:
        try:
            return _fernet.decrypt(stored.encode()).decode()
        except Exception:
            return stored
    return stored


def format_phone_number(phone):
    """Format phone number for WhatsApp"""
    if not phone:
        return None
    phone = str(phone).strip()
    phone = ''.join(filter(str.isdigit, phone))
    if phone.startswith('0'):
        phone = phone[1:]
    if not phone.startswith('91') and len(phone) == 10:
        phone = '91' + phone
    return phone


def _build_header_component(media_url, header_type):
    """
    Build the WhatsApp 'header' component, or return None if this send
    shouldn't have one. header_type must be explicitly 'document', 'image',
    or 'video' — a media_url alone is no longer enough to trigger this,
    because that mismatch (attaching a header to a body-only approved
    template) is what breaks the send.
    """
    if not media_url or header_type not in ("document", "image", "video"):
        return None
    if not isinstance(media_url, str) or not media_url.startswith(('http://', 'https://')):
        return None

    if header_type == "document":
        from urllib.parse import urlparse
        media_path = urlparse(media_url).path
        raw_name = media_path.rsplit('/', 1)[-1] or 'invoice'
        clean_filename = raw_name if '.' in raw_name else f"{raw_name}.pdf"
        return {
            "type": "header",
            "parameters": [{
                "type": "document",
                "document": {"link": media_url, "filename": clean_filename}
            }]
        }
    elif header_type == "image":
        return {
            "type": "header",
            "parameters": [{"type": "image", "image": {"link": media_url}}]
        }
    elif header_type == "video":
        return {
            "type": "header",
            "parameters": [{"type": "video", "video": {"link": media_url}}]
        }
    return None


def _send_whatsapp_template(company, to_number, template_name, params, media_url=None, header_type="none"):
    """
    Send WhatsApp template via MobiCOMM API

    Args:
        company: Company object with WhatsApp settings
        to_number: Recipient phone number
        template_name: Template name in MobiCOMM
        params: List of parameters for the template body (any length)
        media_url: Optional media URL for header attachment (must be HTTPS)
        header_type: 'none' | 'document' | 'image' | 'video' — must match what
                     was actually approved for this template in Meta Business
                     Manager, or the send fails.

    Returns:
        dict: {'success': bool, 'message_id': str, 'error': str}
    """
    # ─── VALIDATION ──────────────────────────────────────────────────────────
    if not company:
        return {'success': False, 'error': 'Company not provided'}

    if not company.whatsapp_enabled:
        return {'success': False, 'error': 'WhatsApp not enabled'}

    if not company.whatsapp_api_key:
        return {'success': False, 'error': 'API key not configured'}

    if not company.whatsapp_base_url:
        return {'success': False, 'error': 'Base URL not configured'}

    to_number = format_phone_number(to_number)
    if not to_number:
        return {'success': False, 'error': 'Invalid phone number'}

    # ─── DECRYPT API KEY ─────────────────────────────────────────────────────
    api_key = decrypt_secret(company.whatsapp_api_key)
    waba_number = company.whatsapp_business_no or ""

    # ─── BUILD PAYLOAD ───────────────────────────────────────────────────────
    components = []

    header_component = _build_header_component(media_url, header_type)
    if header_component:
        components.append(header_component)

    # ─── BODY PARAMETERS (any length — no assumption about count) ───────────
    if params:
        body_params = [{"type": "text", "text": str(p)} for p in params]
        components.append({
            "type": "body",
            "parameters": body_params
        })

    # ─── BUILD FINAL PAYLOAD ─────────────────────────────────────────────────
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "template",
        "template": {
            "language": {
                "policy": "deterministic",
                "code": "en"
            },
            "name": template_name,
            "components": components
        }
    }

    # ─── HEADERS ─────────────────────────────────────────────────────────────
    headers = {
        "Content-Type": "application/json",
        "Key": api_key,
    }

    if waba_number:
        headers["wabaNumber"] = waba_number

    # ─── SEND REQUEST ───────────────────────────────────────────────────────
    url = company.whatsapp_base_url.rstrip('/')

    print(f"[WhatsApp] Sending to: {to_number}")
    print(f"[WhatsApp] Template: {template_name}")
    print(f"[WhatsApp] URL: {url}")
    print(f"[WhatsApp] header_type: {header_type}, media_url: {media_url}")
    print(f"[WhatsApp] Payload: {json.dumps(payload, indent=2)}")

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)

        print(f"[WhatsApp] Response Status: {response.status_code}")
        print(f"[WhatsApp] Response Body: {response.text[:500]}")

        if response.status_code in (200, 201, 202):
            data = response.json()

            if "error" in data:
                return {
                    'success': False,
                    'message_id': None,
                    'error': data.get('error', {}).get('message', 'Unknown API error'),
                    'response': data
                }

            return {
                'success': True,
                'message_id': data.get('message_id') or data.get('id') or data.get('messageId'),
                'response': data,
                'error': None
            }
        else:
            return {
                'success': False,
                'message_id': None,
                'error': f"HTTP {response.status_code}: {response.text}",
                'response': response.text
            }

    except requests.exceptions.Timeout:
        return {'success': False, 'error': 'Request timeout'}
    except requests.exceptions.ConnectionError:
        return {'success': False, 'error': 'Connection error'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def send_booking_confirmation(company, invoice, docket_no, media_url=None, header_type="none"):
    """Send booking confirmation. No PDF attached unless header_type is explicitly set."""
    client = invoice.client_obj if hasattr(invoice, 'client_obj') else None
    to_number = client.phone if client else invoice.phone

    if not to_number:
        return {'success': False, 'error': 'No phone number found'}

    params = [
        docket_no,
        invoice.date.strftime("%d-%b-%Y"),
        company.phone or "",
    ]

    template_name = company.whatsapp_template_generate or "booking_confirmation"

    return _send_whatsapp_template(
        company=company,
        to_number=to_number,
        template_name=template_name,
        params=params,
        media_url=media_url,
        header_type=header_type,
    )


def send_shipment_update(company, invoice, docket_no, status, media_url=None, header_type="none"):
    """Send shipment status update. No PDF attached unless header_type is explicitly set."""
    client = invoice.client_obj if hasattr(invoice, 'client_obj') else None
    to_number = client.phone if client else invoice.phone

    if not to_number:
        return {'success': False, 'error': 'No phone number found'}

    params = [
        docket_no,
        status or invoice.status or "Updated",
        datetime.now().strftime("%d-%b-%Y"),
        company.phone or "",
    ]

    template_name = company.whatsapp_template_update or "shipment_update"

    return _send_whatsapp_template(
        company=company,
        to_number=to_number,
        template_name=template_name,
        params=params,
        media_url=media_url,
        header_type=header_type,
    )


def send_delivery_confirmation(company, invoice, docket_no, media_url=None, header_type="none"):
    """Send delivery confirmation. No PDF attached unless header_type is explicitly set."""
    client = invoice.client_obj if hasattr(invoice, 'client_obj') else None
    to_number = client.phone if client else invoice.phone

    if not to_number:
        return {'success': False, 'error': 'No phone number found'}

    params = [
        docket_no,
        datetime.now().strftime("%d-%b-%Y"),
        company.phone or "",
    ]

    template_name = company.whatsapp_template_delivery or "delivery_confirmation"

    return _send_whatsapp_template(
        company=company,
        to_number=to_number,
        template_name=template_name,
        params=params,
        media_url=media_url,
        header_type=header_type,
    )


def _try_generic_connector(company, to_number, template_name, params, language_code="en", media_url=None, header_type="none"):
    """
    Returns a result dict if this company is migrated to the generic connector
    (has a CompanyWhatsAppConfig row), or None if it isn't.
    """
    try:
        from platform_models import CompanyWhatsAppConfig, WhatsAppProviderDefinition
        from whatsapp_connector import send_via_definition, ConnectorConfigError, ConnectorSecurityError
    except ImportError:
        return None

    cfg = CompanyWhatsAppConfig.query.filter_by(company_id=company.company_id, enabled=True).first()
    if not cfg:
        return None

    provider_def = cfg.provider_definition or WhatsAppProviderDefinition.query.get(cfg.provider_definition_id)
    if not provider_def or not provider_def.is_active:
        return {"success": False, "error": f"Provider definition inactive or missing for {company.company_id}"}

    try:
        credentials = json.loads(decrypt_secret(cfg.credentials_encrypted) or "{}")
        extra_config = json.loads(decrypt_secret(cfg.extra_config_encrypted) or "{}") if cfg.extra_config_encrypted else {}
    except (ValueError, TypeError) as e:
        return {"success": False, "error": f"Could not parse stored credentials: {e}"}

    try:
        return send_via_definition(
            provider_def=provider_def,
            credentials=credentials,
            extra_config=extra_config,
            to_number=format_phone_number(to_number),
            template_name=template_name,
            params=params,
            language_code=language_code,
        )
    except (ConnectorConfigError, ConnectorSecurityError) as e:
        return {"success": False, "error": str(e)}


def send_carrier_update(company, invoice, docket_no, client_name, carrier, carrier_ref, media_url=None, header_type="none"):
    """Send carrier-reference-updated notification"""
    client = invoice.client_obj if hasattr(invoice, 'client_obj') else None
    to_number = client.phone if client else invoice.phone

    if not to_number:
        return {'success': False, 'error': 'No phone number found'}

    params = [
        client_name or "Customer",
        docket_no,
        carrier_ref,
        carrier or "",
    ]

    template_name = company.whatsapp_template_carrier_update or "carrier_reference_update"

    return _send_whatsapp_template(
        company=company,
        to_number=to_number,
        template_name=template_name,
        params=params,
        media_url=media_url,
        header_type=header_type,
    )


def build_manual_whatsapp_link(to_number, message):
    """Build wa.me link for manual sending"""
    import urllib.parse
    digits = ''.join(filter(str.isdigit, to_number or ''))
    return f"https://wa.me/{digits}?text={urllib.parse.quote(message)}"


def send_or_manual(company, to_number, template_name, params, fallback_message, language_code="en",
                    media_url=None, header_type="none"):
    """
    Unified entry point: try generic-connector config first, then legacy MobiCOMM,
    then fall back to a manual wa.me link.

    Args:
        media_url: Optional URL to a document/image/video to attach.
        header_type: 'none' | 'document' | 'image' | 'video'. Must match what the
                     company's approved template actually supports — a mismatch
                     here is what causes silent send failures, not a media_url
                     being present or absent.
    """
    print(f"[WhatsApp Debug] company: {company.company_id if company else 'None'}")
    print(f"[WhatsApp Debug] to_number: {to_number}")
    print(f"[WhatsApp Debug] template_name: {template_name}")
    print(f"[WhatsApp Debug] params ({len(params) if params else 0}): {params}")
    print(f"[WhatsApp Debug] header_type: {header_type}, media_url: {media_url}")

    if company and getattr(company, "whatsapp_enabled", False):
        generic_result = _try_generic_connector(
            company, to_number, template_name, params, language_code, media_url, header_type
        )

        if generic_result is not None:
            if generic_result.get("success"):
                return {"sent": True, "manual_link": None, "error": None,
                        "message_id": generic_result.get("message_id")}
            return {
                "sent": False,
                "manual_link": build_manual_whatsapp_link(to_number, fallback_message),
                "error": generic_result.get("error"),
            }

        # Not migrated — legacy MobiCOMM path
        if company.whatsapp_provider:
            try:
                result = _send_whatsapp_template(
                    company=company,
                    to_number=to_number,
                    template_name=template_name,
                    params=params,
                    media_url=media_url,
                    header_type=header_type,
                )
            except NotImplementedError as e:
                result = {"sent": False, "provider_msg_id": None, "error": str(e)}

            if result.get("success"):
                return {"sent": True, "manual_link": None, "error": None, "message_id": result.get("message_id")}

            return {
                "sent": False,
                "manual_link": build_manual_whatsapp_link(to_number, fallback_message),
                "error": result.get("error"),
            }

    # No API configured - manual link only
    return {
        "sent": False,
        "manual_link": build_manual_whatsapp_link(to_number, fallback_message),
        "error": "whatsapp_not_configured",
    }
