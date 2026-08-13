"""
Drop-in guard for ai_assistant.py.

PURPOSE: prevent the free-text LLM fallback from ever answering a
finance/data-shaped question with an improvised number or a false claim
about where its data came from (see: the net-profit responses that
claimed access to "public information" about the company).

WHERE THIS GOES: inside self_learning_ai.py's chat() method, insert the
check BETWEEN step 2 (keyword router dispatch) and the fallback to
self._general_answer(user_message). I don't have ai_assistant.py yet,
so I can't wire this into the exact method signature — this is the
logic, not a verified patch.
"""

import re

# Keywords that signal "this question is asking about the company's
# actual numbers" — if a message matches one of these AND the router
# returned no intent, it must NEVER go to the free-text LLM.
_FINANCE_SHAPED = re.compile(
    r"(?i)\b("
    r"profit|revenue|expense|balance|pending|receivable|payable|"
    r"outstanding|gst|tax|cash|bank|loan|emi|invoice|bill|stock|"
    r"inventory|turnover|income|earning|owe|paid|payment|due|"
    r"collect|dues|amount"
    r")\b"
)

FINANCE_FALLBACK_MESSAGE = (
    "I don't have a way to answer that yet — I can't calculate or guess "
    "at company figures I haven't been given a direct query for. "
    "Try rephrasing (e.g. \"pending receivables\", \"total expenses\", "
    "\"gst summary\"), or ask your admin to add this as a supported query."
)


def is_finance_shaped(message: str) -> bool:
    """True if the message looks like it's asking about real company
    numbers, even though the deterministic router didn't classify it."""
    return bool(_FINANCE_SHAPED.search(message or ""))


# ── Example of where this plugs into self_learning_ai.py's chat() ──
#
#   data = dispatch(user_message, company_id)
#   ...
#   if data.get("intent"):
#       return self._build_response(data, user_message)
#
#   # NEW — insert here, before falling through to the LLM:
#   if is_finance_shaped(user_message):
#       return {
#           "response": FINANCE_FALLBACK_MESSAGE,
#           "data": None,
#           "source": "finance_guard",
#       }
#
#   response = self._general_answer(user_message)
#   return {"response": response, "data": None, "source": "ai_fallback"}
