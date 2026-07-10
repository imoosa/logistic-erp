"""
whatsapp_connector.py
──────────────────────
Generic, config-driven WhatsApp sender.

Scope, deliberately: static API-key / Bearer-token REST providers that accept
a single JSON or form-encoded POST and return a JSON response. This does NOT
cover OAuth2 refresh flows, HMAC-signed requests, or multi-step media-upload
sends — those still need a hand-written function (see whatsapp_service.py's
PROVIDER_HANDLERS registry for that escape hatch).

Nothing here replaces the MobiCOMM path in whatsapp_service.py. A company only
goes through this connector once it has a CompanyWhatsAppConfig row pointing
at a WhatsAppProviderDefinition. Everyone else keeps working exactly as before.
"""

import re
import json
import requests

PLACEHOLDER_FULL_RE = re.compile(r'^\{\{\s*([\w.]+)\s*\}\}$')
PLACEHOLDER_ANY_RE = re.compile(r'\{\{\s*([\w.]+)\s*\}\}')


class ConnectorConfigError(Exception):
    """Raised when a provider definition or company config is malformed."""
    pass


class ConnectorSecurityError(Exception):
    """Raised when a rendered URL fails the allowed_hosts check."""
    pass


def _resolve_path(ctx, path):
    """Resolve a dotted path like 'config.phone_id' against a dict-of-dicts context."""
    val = ctx
    for part in path.split('.'):
        if isinstance(val, dict):
            if part not in val:
                raise ConnectorConfigError(f"Placeholder path '{path}' not found in context (missing '{part}')")
            val = val[part]
        else:
            val = getattr(val, part)
    return val


def render_value(value, ctx):
    """
    Recursively render {{ placeholder }} references in a JSON-like structure.

    - A string that is ENTIRELY a single placeholder (e.g. "{{ components }}")
      is replaced with the raw resolved object — list/dict/int types survive.
    - A string with a placeholder embedded in other text (e.g. "Bearer {{ secret.token }}")
      gets string substitution only.
    - dict/list are walked recursively. Anything else is returned unchanged.
    """
    if isinstance(value, str):
        full_match = PLACEHOLDER_FULL_RE.match(value.strip())
        if full_match:
            return _resolve_path(ctx, full_match.group(1))
        if PLACEHOLDER_ANY_RE.search(value):
            return PLACEHOLDER_ANY_RE.sub(lambda m: str(_resolve_path(ctx, m.group(1))), value)
        return value
    if isinstance(value, dict):
        return {k: render_value(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(v, ctx) for v in value]
    return value


def _dig(data, path):
    """Walk a dotted path (numeric parts index into lists) into a parsed JSON response."""
    if not path:
        return None
    cur = data
    for part in path.split('.'):
        if cur is None:
            return None
        if isinstance(cur, list):
            if not part.isdigit():
                return None
            idx = int(part)
            cur = cur[idx] if 0 <= idx < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def validate_url(url, allowed_hosts_csv):
    """Reject if the rendered URL's host isn't in the provider's allowlist."""
    if not allowed_hosts_csv:
        return  # provider definition didn't restrict — super-admin's call, not ours to second-guess here
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    allowed = [h.strip().lower() for h in allowed_hosts_csv.split(',') if h.strip()]
    if host.lower() not in allowed:
        raise ConnectorSecurityError(f"URL host '{host}' is not in allowed_hosts {allowed}")


def send_via_definition(provider_def, credentials, extra_config, to_number, template_name,
                         params, language_code="en"):
    """
    provider_def: WhatsAppProviderDefinition instance
    credentials: dict, already decrypted (e.g. {"api_key": "...", "access_token": "..."})
    extra_config: dict, already decrypted (e.g. {"phone_id": "...", "waba_number": "..."})

    Returns: {'success': bool, 'message_id': str|None, 'error': str|None, 'raw_status': int|None}
    """
    ctx = {
        "to_number": to_number,
        "template_name": template_name,
        "language_code": language_code,
        "params": [str(p) for p in (params or [])],
        "components": [
            {"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in (params or [])]}
        ],
        "secret": credentials or {},
        "config": extra_config or {},
    }

    try:
        headers_tpl = json.loads(provider_def.headers_template)
        body_tpl = json.loads(provider_def.body_template)
    except (ValueError, TypeError) as e:
        raise ConnectorConfigError(f"Provider '{provider_def.provider_code}' has invalid JSON template: {e}")

    url = render_value(provider_def.url_template, ctx)
    validate_url(url, provider_def.allowed_hosts)

    headers = render_value(headers_tpl, ctx)
    body = render_value(body_tpl, ctx)

    encoding = (provider_def.body_encoding or "json").lower()
    timeout = provider_def.timeout_seconds or 30

    try:
        if encoding == "form":
            resp = requests.request(provider_def.method or "POST", url, headers=headers, data=body, timeout=timeout)
        else:
            resp = requests.request(provider_def.method or "POST", url, headers=headers, json=body, timeout=timeout)
    except requests.exceptions.Timeout:
        return {'success': False, 'message_id': None, 'error': 'Request timeout', 'raw_status': None}
    except requests.exceptions.ConnectionError:
        return {'success': False, 'message_id': None, 'error': 'Connection error', 'raw_status': None}
    except Exception as e:
        return {'success': False, 'message_id': None, 'error': str(e), 'raw_status': None}

    try:
        data = resp.json()
    except ValueError:
        data = {}

    allowed_codes = [int(c.strip()) for c in (provider_def.success_status_codes or "200").split(',') if c.strip()]
    status_ok = resp.status_code in allowed_codes

    success = status_ok
    if success and provider_def.success_path:
        actual = _dig(data, provider_def.success_path)
        if provider_def.success_expected_value is not None and provider_def.success_expected_value != "":
            success = (str(actual) == str(provider_def.success_expected_value))
        else:
            success = bool(actual)

    if success:
        message_id = _dig(data, provider_def.message_id_path) if provider_def.message_id_path else None
        return {'success': True, 'message_id': message_id, 'error': None, 'raw_status': resp.status_code}

    error_msg = _dig(data, provider_def.error_path) if provider_def.error_path else None
    if not error_msg:
        error_msg = f"HTTP {resp.status_code}: {resp.text[:300]}"
    return {'success': False, 'message_id': None, 'error': error_msg, 'raw_status': resp.status_code}
