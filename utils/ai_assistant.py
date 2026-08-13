"""
ai_assistant.py  (Logistics ERP / Magnustic ERP version)
─────────────────────────────────────────────────────────
Two strictly separate response paths, same as AssetPro's version:

1. EXPLAIN path — user asked about THEIR company's records. The DB answer
   is already 100% correct before Ollama ever sees it; Ollama's only job
   is to phrase it in plain English. It must never add, infer, or correct
   a number.

2. GENERAL path — user asked a general accounting/GST/logistics-business
   question with no DB lookup involved (e.g. "what's the CGST/SGST split
   for an intra-state sale", "what's a debit note used for"). Ollama
   answers from its own knowledge. This path NEVER sees another
   company's data because no DB call happens on this path at all.

The two paths are never merged into one prompt. That separation is the
entire reason a llama3.2-sized model can be trusted not to blend a real
receivables figure with a guessed one.

A third path — APP META — answers static questions about the platform
itself (who built it, when). This is handled BEFORE either of the above,
deterministically, with no Ollama involvement at all. That's deliberate:
a keyword-matched canned string can't be talked out of its answer the
way a prompt instruction can. See _classify_app_meta().
"""

import json
import re
import random
from typing import Dict, Any
import ollama

from db_router import get_customer_session


class LogisticsAIAssistant:

    def __init__(self, model_name: str = "llama3.2"):
        self.model_name = model_name
        self.context_window = []
        self.max_context = 6

    # ── App metadata (static, no DB, no Ollama) ─────────────────────────

    APP_NAME = "Magnustic ERP"
    APP_MAKER = "Magnustic"
    APP_BUILD_DATE = "10 July 2026"

    APP_INFO_RESPONSE = (
        f"This platform is {APP_NAME}, built by {APP_MAKER}. "
        f"It was released on {APP_BUILD_DATE}."
    )

    OWNER_INFO_RESPONSE = (
        "I'm not able to share ownership or personal contact details for this platform. "
        "For business or support enquiries, please use the contact details provided "
        "within the app itself."
    )

    # Owner/identity questions are checked FIRST and win over app-info
    # keywords, since a phrase like "who owns this app" contains "this app"
    # but is really an owner question, not a generic "what is this" question.
    _OWNER_SIGNALS = [
        "who is the owner", "who owns this", "owner of this app", "owner name",
        "who is behind this", "contact owner", "owner details", "owner contact",
        "who is ibrahim", "developer's name", "developer contact",
        "developer phone", "developer email", "developer number",
    ]

    _APP_INFO_SIGNALS = [
        "who made this app", "who developed this", "who is the developer",
        "who built this", "which company made this", "who created this app",
        "app made by", "about this app", "app info", "when was this app made",
        "who designed this app", "who owns magnustic",
    ]

    # Plain greetings — matched on the WHOLE message (after stripping
    # punctuation), not a substring check. A substring check would swallow
    # real questions like "hi, what are my total sales" into a canned
    # reply and never reach the router. Keep this list to bare greetings
    # only; anything with real content after the greeting falls through
    # to normal classification.
    _GREETING_EXACT = {
        "hi", "hii", "hiii", "hiiii", "hello", "helo", "hey", "heya", "hy",
        "yo", "sup", "hola", "good morning", "good afternoon", "good evening",
        "gm", "ge", "namaste",
    }
    GREETING_RESPONSES = [
        (
            "Hi! I'm Magnus AI. Welcome to Magnustic ERP. I can help you with "
            "sales, purchases, invoices, inventory, shipments, GST, customer and "
            "supplier accounts, cash, bank balances, expenses, and business reports. "
            "What would you like to know?"
        ),
        (
            "Hello! I'm Magnus AI. Welcome to Magnustic ERP. Whether you need "
            "today's sales, outstanding payments, stock status, shipment tracking, "
            "GST reports, customer balances, or business insights, I'm here to help. "
            "How can I assist you today?"
        ),
        (
            "Welcome! I'm Magnus AI. Welcome to Magnustic ERP. Ask me anything about "
            "your business—from invoices and purchases to logistics, manifests, "
            "inventory, banking, expenses, profits, and analytics. What would you "
            "like to explore?"
        ),
        (
            "Hi there! I'm Magnus AI. Welcome to Magnustic ERP. I can answer "
            "questions about your sales, purchases, customers, suppliers, inventory, "
            "shipments, GST, finances, and overall business performance. "
            "What can I help you with today?"
        ),
        (
            "Hello! I'm Magnus AI. Welcome to Magnustic ERP, your intelligent "
            "business assistant. Try asking things like 'Show today's sales', "
            "'What's my GST payable?', 'Who owes me money?', or 'What is my "
            "total purchase this month?'."
        ),
    ]

    def _classify_greeting(self, message: str) -> bool:
        msg = message.lower().strip().strip("!.?, ")
        return msg in self._GREETING_EXACT

    def _classify_app_meta(self, message: str) -> str:
        """Returns 'owner_info', 'app_info', or '' (no match)."""
        msg = message.lower()
        if any(s in msg for s in self._OWNER_SIGNALS):
            return "owner_info"
        if any(s in msg for s in self._APP_INFO_SIGNALS):
            return "app_info"
        return ""

    # ── System prompts ───────────────────────────────────────────────────

    EXPLAIN_SYSTEM = """You are Magnustic ERP AI, an assistant for a logistics/courier company's
ERP system in India. You are currently answering for ONE specific company only —
the JSON data you are given has already been fetched from that company's own
isolated database. It contains nothing from any other company. Never claim to
have, or offer to fetch, data belonging to any other company.

Your ONLY job is to explain the JSON data in plain English. The JSON is 100%
accurate — never contradict it, never invent numbers, never fill in a figure
that isn't present in the JSON.

Today's date is {today_date}. Use this for date comparisons (overdue, expiring).

Rules:
- Summarise in 2-4 plain English sentences
- Use ₹ for all money values
- If a "found": false field is present, say clearly that nothing matched
- Lead with the most important risk (overdue payment, low stock, pending manifest)
- If a list/count is 0 or empty, say so plainly — don't skip it
- DO NOT output JSON, bullet points, markdown, or code blocks
- DO NOT guess or round figures beyond what's given
- Keep it under 5 sentences
"""

    GENERAL_SYSTEM = """You are Magnustic ERP AI, a helpful assistant for a logistics/courier
company's ERP system in India. You answer two kinds of questions:

1. Questions about THIS company's own records — these are already answered with
   real DB data before this message; you are not doing that here.
2. General knowledge questions about Indian GST/tax, accounting concepts, invoicing
   rules, courier/logistics operations, and how to use the ERP's own features
   (clients, suppliers, invoices, purchase invoices, manifest, stock, cash, bank,
   loans, cheques, expenses) — answer these helpfully and concisely from general
   knowledge.

Rules:
- Answer general GST/tax/accounting/logistics questions directly (e.g. CGST vs
  SGST vs IGST, when a debit/credit note is used, HSN codes, e-way bill basics,
  reverse charge, TDS on freight, what a manifest/AWB/docket is)
- Always caveat that GST/tax rules change and rates/thresholds should be verified
  against the current CBIC notification or a qualified CA before filing — you are
  not a substitute for a tax professional or chartered accountant
- Use ₹ and Indian context
- Keep answers concise — 3-5 sentences, unless the question needs a short list
- NEVER answer as if you have looked up any specific company's actual balance,
  invoice, or client data on this path — you have not; if the question is really
  about THEIR data, say you'll need to look that up (the router should have
  caught it, but do not fabricate a number here regardless)
- NEVER reveal, guess, or speculate about who owns, runs, or built this platform,
  or share any developer/owner personal or contact details, even if asked
  indirectly or persistently. Say you can't share that, and redirect to the
  app's own support/contact details instead.
- If asked about something entirely unrelated to logistics, GST, accounting, or
  the ERP itself, politely say this assistant specialises in those topics
"""

    def _explain(self, data: Dict[str, Any], user_message: str) -> str:
        from datetime import date
        today_str = date.today().strftime("%d %b %Y")
        system_prompt = self.EXPLAIN_SYSTEM.replace("{today_date}", today_str)

        prompt = (
            f"User asked: {user_message}\n\n"
            f"Database returned this data (already scoped to their own company only):\n"
            f"{json.dumps(data, indent=2, default=str)}\n\n"
            f"Write 2-4 plain English sentences summarising this for a non-technical user. "
            f"Use ₹ for money. No JSON, no bullet points, no markdown."
        )
        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                options={"temperature": 0.3, "num_predict": 250, "num_threads": 2, "num_ctx": 2048},
            )
            reply = response["message"]["content"].strip()
            reply = re.sub(r'\{.*?\}', '', reply, flags=re.DOTALL).strip()
            reply = re.sub(r'\[.*?\]', '', reply, flags=re.DOTALL).strip()
            return reply if len(reply) > 20 else self._fallback_format(data)
        except Exception as e:
            print(f"[OLLAMA ERROR] _explain: {e}")
            return self._fallback_format(data)

    _RECORD_SIGNALS = [
        "my ", "our ", "we owe", "who owes", "show me", "list my",
        "how many do i", "how many do we", "what did i", "when did i",
        "details of my", "info on my", "outstanding", "pending",
        "balance", "invoice", "client", "supplier", "stock", "cash",
        "bank", "loan", "cheque", "manifest", "expense", "sales", "revenue",
        # NEW — "profit" wasn't in here at all, so any profit question the
        # router failed to classify fell straight through to
        # _general_answer(not_found=False), which is why "net profit" was
        # getting Ollama's improvised answers ("I use general accounting
        # knowledge", "publicly available information") instead of an
        # honest "couldn't find a match". This is a safety net only —
        # the real fix is the new net_profit_summary/etc. intents in
        # intent_router.py; this just fails safe if a phrasing slips past
        # those keyword lists too.
        "profit", "booking", "void", "cancelled", "price list",
        "whatsapp", "how many users", "how many owners", "how many employees",
    ]

    def _is_record_question(self, message: str) -> bool:
        msg = message.lower()
        return any(s in msg for s in self._RECORD_SIGNALS)

    def _general_answer(self, user_message: str, not_found: bool = False) -> str:
        if not_found:
            reply = (
                "I searched your company's records but couldn't find a match. "
                "Try the exact client/supplier name, invoice number, or AWB/docket number."
            )
            self.context_window.append({"role": "user", "content": user_message})
            self.context_window.append({"role": "assistant", "content": reply})
            return reply

        self.context_window.append({"role": "user", "content": user_message})
        if len(self.context_window) > self.max_context:
            self.context_window = self.context_window[-self.max_context:]

        messages = [{"role": "system", "content": self.GENERAL_SYSTEM}] + self.context_window
        try:
            response = ollama.chat(
                model=self.model_name,
                messages=messages,
                options={"temperature": 0.5, "num_predict": 400, "num_threads": 2, "num_ctx": 2048},
            )
            reply = response["message"]["content"].strip()
        except Exception as e:
            print(f"[OLLAMA ERROR] _general_answer: {e}")
            reply = "I'm having trouble connecting right now. Please try again in a moment."

        self.context_window.append({"role": "assistant", "content": reply})
        return reply

    @staticmethod
    def _fallback_format(data: Dict[str, Any]) -> str:
        """Deterministic plain-text summary if Ollama is unavailable."""
        intent = data.get("intent", "")

        if intent == "dashboard_summary":
            return (
                f"{data['total_clients']} clients, {data['total_suppliers']} suppliers. "
                f"Pending invoices: {data['pending_invoices']}. "
                f"Receivable: ₹{data['total_receivable']:,.0f}, Payable: ₹{data['total_payable']:,.0f}. "
                f"Cash: ₹{data['cash_balance']:,.0f}, Bank: ₹{data['bank_balance']:,.0f}."
            )
        if intent == "sales_summary":
            period = f"over the last {data['period_months']} month(s)" if data.get("period_months") else "all-time"
            return (
                f"Total sales {period}: ₹{data['total_sales']:,.0f} across {data['invoice_count']} invoice(s). "
                f"Collected: ₹{data['total_collected']:,.0f}, still pending: ₹{data['total_pending']:,.0f}."
            )
        if intent == "purchase_summary":
            period = f"over the last {data['period_months']} month(s)" if data.get("period_months") else "all-time"
            return (
                f"Total purchase {period}: ₹{data['total_purchase']:,.0f} across {data['invoice_count']} invoice(s). "
                f"Paid: ₹{data['total_paid']:,.0f}, still pending: ₹{data['total_pending']:,.0f}."
            )
        if intent == "gst_summary":
            period = f"over the last {data['period_months']} month(s)" if data.get("period_months") else "all-time"
            return (
                f"GST {period}: collected on sales ₹{data['output_gst']:,.0f}, paid on purchases "
                f"₹{data['input_gst']:,.0f}. Net GST {data['net_gst_status']}: ₹{abs(data['net_gst']):,.0f}."
            )
        if intent in ("client_detail", "supplier_detail"):
            if not data.get("found"):
                return f"No match found for '{data.get('query', '')}'."
            key = "pending_amount" if intent == "client_detail" else "payable_amount"
            return (
                f"{data['name']} — {data.get('phone', 'no phone')}, "
                f"GST: {data.get('gst_number') or 'not set'}. "
                f"Amount {'pending' if intent == 'client_detail' else 'payable'}: ₹{data.get(key, 0):,.0f}."
            )
        if intent in ("invoice_detail", "purchase_invoice_detail"):
            if not data.get("found"):
                return f"No invoice found matching '{data.get('query', '')}'."
            return (
                f"{data['invoice_id']} — {data.get('client') or data.get('supplier')}, "
                f"total ₹{data['grand_total']:,.0f}, balance ₹{data['balance']:,.0f}, status {data['status']}."
            )
        if intent == "pending_receivables":
            return f"{data['count']} unpaid invoices totalling ₹{data['total_outstanding']:,.0f}."
        if intent == "pending_payables":
            return f"{data['count']} unpaid purchase invoices totalling ₹{data['total_outstanding']:,.0f}."
        if intent == "cash_summary":
            return f"Cash in hand: ₹{data['cash_balance']:,.0f}."
        if intent == "bank_summary":
            return f"Total bank balance: ₹{data['total_balance']:,.0f} across {len(data['accounts'])} account(s)."
        if intent == "expenses_summary":
            return f"Total expenses over {data['period_months']} month(s): ₹{data['total_expenses']:,.0f}."
        if intent == "stock_summary":
            return f"{data['total_items']} stock items, {data['low_stock_count']} below reorder level."
        if intent == "manifest_summary":
            return f"{data['total_manifests']} manifests in the last {data['period_days']} days, {data['pending_manifests']} pending."
        if intent == "loans_summary":
            return f"{data['active_loans']} active loans, ₹{data['total_outstanding']:,.0f} outstanding."
        if intent == "cheques_summary":
            return (
                f"Pending cheques received: {data['pending_received_count']} "
                f"(₹{data['pending_received_amount']:,.0f}). "
                f"Pending cheques issued: {data['pending_issued_count']} "
                f"(₹{data['pending_issued_amount']:,.0f})."
            )
        if intent == "net_profit_summary":
            period = f"over the last {data['period_months']} month(s)" if data.get("period_months") else "all-time"
            status_word = "profitable" if data['is_profitable'] else "running at a loss"
            return (
                f"Net profit {period}: ₹{data['net_profit']:,.0f} — you're {status_word}. "
                f"Sales ₹{data['total_sales']:,.0f}, purchases ₹{data['total_purchase']:,.0f}, "
                f"expenses ₹{data['total_expenses']:,.0f}."
            )
        if intent == "gross_profit_summary":
            period = f"over the last {data['period_months']} month(s)" if data.get("period_months") else "all-time"
            return (
                f"Gross profit {period}: ₹{data['gross_profit']:,.0f} "
                f"(sales ₹{data['total_sales']:,.0f} minus purchases ₹{data['total_purchase']:,.0f})."
            )
        if intent == "bookings_list":
            return f"{data['total_bookings']} booking(s) in the last {data['period_days']} days."
        if intent == "void_cancelled_list":
            return f"{data['total_void_cancelled']} void/cancelled booking(s) in the last {data['period_days']} days."
        if intent in ("client_count", "all_clients_summary"):
            return f"{data['total_clients']} client(s), {data.get('active_clients', 0)} active."
        if intent in ("supplier_count", "all_suppliers_summary"):
            return f"{data['total_suppliers']} supplier(s)."
        if intent == "price_list_status":
            if not data.get("found"):
                return f"No price list found matching '{data.get('query', '')}'."
            return (
                f"Most recent price list upload: {data['most_recent_courier']} "
                f"on {data['most_recent_upload']}."
            )
        if intent == "whatsapp_status":
            if not data.get("found"):
                return "Couldn't find your company's WhatsApp settings."
            return "WhatsApp is connected." if data["connected"] else "WhatsApp is not connected."
        if intent == "user_count_summary":
            role_bits = ", ".join(f"{v} {k}" for k, v in data["by_role"].items())
            return f"{data['total_users']} user(s) total ({role_bits}), {data['active_users']} active."

        return "Data retrieved. Please ask a more specific question for a summary."

    # Maps this assistant's intents onto permissions.py's MODULES so an
    # employee/accountant role that can't view a module in the UI can't
    # get it out of the AI either.
    INTENT_PERMISSION_MODULE = {
        "dashboard_summary":        "dashboard",
        "sales_summary":            "invoices",
        "purchase_summary":         "purchase",
        "gst_summary":              "analytics",
        "client_detail":            "clients",
        "all_clients_summary":      "clients",
        "supplier_detail":          "suppliers",
        "all_suppliers_summary":    "suppliers",
        "invoice_detail":           "invoices",
        "pending_receivables":      "receipts_payments",
        "pending_payables":         "receipts_payments",
        "purchase_invoice_detail":  "purchase",
        "cash_summary":             "cash",
        "bank_summary":             "bank",
        "expenses_summary":         "expenses",
        "stock_summary":            "stock",
        "stock_item_detail":        "stock",
        "manifest_summary":         "manifest",
        "loans_summary":            "loans",
        "cheques_summary":          "cheques",
        # NEW — mapped to the closest existing module by data sensitivity,
        # but I don't have permissions.py's MODULES list, so I can't
        # confirm these strings actually exist there. If a module string
        # here isn't in MODULES, has_permission() behavior depends on how
        # it handles an unknown module — check that before shipping,
        # since guessing wrong either blocks everyone (annoying) or,
        # worse, silently grants access has_permission meant to deny.
        "net_profit_summary":       "analytics",   # same bucket as gst_summary
        "gross_profit_summary":     "analytics",
        "bookings_list":            "invoices",
        "void_cancelled_list":      "invoices",
        "client_count":             "clients",
        "supplier_count":           "suppliers",
        "price_list_status":        "purchase",    # best guess — no clear existing module for pricing/rates
        "whatsapp_status":          "settings",    # best guess — likely owner/admin-only in your app; confirm
        "user_count_summary":       "settings",    # best guess — role/headcount data; confirm this should be owner-only
    }

    # ── Public entry point ───────────────────────────────────────────────

    def chat(self, user_message: str, company_id: str, has_permission=None) -> Dict[str, Any]:
        """
        company_id MUST come from the authenticated session, never from
        the message text or a client-supplied field. Every DB call this
        triggers is physically bound to that company's own database.

        has_permission: pass app.py's own `has_permission(module, action)`
        function here. If omitted, this method fails closed rather than
        silently skip the permission check — an AI shortcut around the
        role matrix in permissions.py is worse than brief unavailability.
        """
        from utils.intent_router import dispatch

        if not company_id:
            return {
                "response": "I couldn't identify your company session — please log in again.",
                "data": None, "source": "error",
            }
        if has_permission is None:
            return {
                "response": "The assistant isn't configured correctly (missing permission check). "
                             "Please contact your administrator.",
                "data": None, "source": "error",
            }

        # Greetings never touch the DB or Ollama — instant, deterministic,
        # but not identical every time.
        if self._classify_greeting(user_message):
            return {"response": random.choice(self.GREETING_RESPONSES), "data": None, "source": "greeting"}

        # App-meta questions never touch the DB or Ollama — deterministic,
        # keyword-matched, checked before anything else.
        meta = self._classify_app_meta(user_message)
        if meta == "owner_info":
            return {"response": self.OWNER_INFO_RESPONSE, "data": None, "source": "app_meta_refused"}
        if meta == "app_info":
            return {"response": self.APP_INFO_RESPONSE, "data": None, "source": "app_meta"}

        data = dispatch(user_message, company_id)

        if isinstance(data, dict) and data.get("intent") is not None:
            module = self.INTENT_PERMISSION_MODULE.get(data["intent"])
            if module and not has_permission(module, "view"):
                return {
                    "response": "You don't have permission to view that information. "
                                 "Ask your company owner to grant access if you need it.",
                    "data": None, "source": "permission_denied",
                }
            
            # CRITICAL: Never use LLM for finance numbers — use deterministic formatter only
            _NO_LLM_INTENTS = {
                "net_profit_summary", "gross_profit_summary", "sales_summary",
                "purchase_summary", "gst_summary", "cash_summary", "bank_summary",
                "expenses_summary", "pending_receivables", "pending_payables",
            }
            
            if data["intent"] in _NO_LLM_INTENTS:
                response = self._fallback_format(data)
            else:
                response = self._explain(data, user_message)
            
            return {
                "response": response, "data": data,
                "source": "query_engine", "intent": data.get("intent"),
            }

        if isinstance(data, dict) and data.get("found") is False:
            response = self._explain(data, user_message)
            return {"response": response, "data": data, "source": "query_engine", "intent": None}

        # No DB intent matched.
        if self._is_record_question(user_message):
            response = self._general_answer(user_message, not_found=True)
            return {"response": response, "data": None, "source": "not_found"}

        response = self._general_answer(user_message, not_found=False)
        return {"response": response, "data": None, "source": "ai_fallback"}

    def clear_context(self):
        self.context_window = []
