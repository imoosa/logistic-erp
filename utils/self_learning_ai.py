"""
AssetPro Self-Learning AI
Wraps AIAssistant with pattern learning.
Learning activates after 10 successful interactions to avoid noise.
"""

import json
import re
import random
from typing import Dict, Any, List, Optional
from datetime import datetime
from collections import defaultdict

from .ai_assistant import LogisticsAIAssistant


class SelfLearningAssetAI(LogisticsAIAssistant):

    def __init__(self, model_name: str = "llama3.2"):
        super().__init__(model_name)
        self.learned_patterns: Dict[str, Any] = {}
        self.feedback_cache: List[Dict] = []
        self.learning_file = "learned_patterns.json"
        self.intent_map_file = "intent_map_updates.json"

        self._load_learned_patterns()
        self._load_intent_updates()

    # ── Public entry point ────────────────────────────────────────────────────

    def chat(self, user_message: str, company_id: int) -> Dict[str, Any]:
        if self._classify_greeting(user_message):
            return {"response": random.choice(self.GREETING_RESPONSES), "data": None, "source": "greeting"}

        meta = self._classify_app_meta(user_message)
        if meta == "owner_info":
            return {"response": self.OWNER_INFO_RESPONSE, "data": None, "source": "app_meta_refused"}
        if meta == "app_info":
            return {"response": self.APP_INFO_RESPONSE, "data": None, "source": "app_meta"}
        try:
            # 1. Try learned patterns first
            learned_intent = self._classify_with_learned_patterns(user_message)
            if learned_intent:
                data = self._dispatch_with_intent(user_message, company_id, learned_intent)
                if isinstance(data, dict) and data.get("intent"):
                    self._store_interaction(user_message, data, "learned_pattern")
                    return self._build_response(data, user_message)

            # 2. Fall back to keyword router
            from .intent_router import dispatch
            data = dispatch(user_message, company_id)
            print(f"[DEBUG] dispatch → intent={data.get('intent') if isinstance(data, dict) else 'N/A'}")

            if not isinstance(data, dict):
                response = self._general_answer(user_message)
                return {"response": response, "data": None, "source": "ai_fallback"}

            # 3. Store for learning
            self._store_interaction(user_message, data, "router")

            # 4. Batch-update patterns every 10 interactions
            if len(self.feedback_cache) >= 10:
                self._update_learned_patterns()
                self._update_intent_map()

            # 5. Return response
            if data.get("intent"):
                return self._build_response(data, user_message)

            response = self._general_answer(user_message)
            return {"response": response, "data": None, "source": "ai_fallback"}

        except Exception as e:
            print(f"[ERROR] SelfLearningAssetAI.chat: {e}")
            import traceback
            traceback.print_exc()
            return {
                "response": "I encountered an error. Please try again.",
                "data": None,
                "source": "error",
            }

    def give_feedback(self, user_message: str, rating: int):
        key = user_message.lower().strip()
        if key in self.learned_patterns and isinstance(self.learned_patterns[key], dict):
            self.learned_patterns[key].setdefault("ratings", []).append(rating)
            ratings = self.learned_patterns[key]["ratings"]
            self.learned_patterns[key]["avg_rating"] = sum(ratings) / len(ratings)
            self._save_learned_patterns()

    # ── Internal helpers ──────────────────────────────────────────────────────

    _NO_LLM_INTENTS = {
        "net_profit_summary", "gross_profit_summary", "sales_summary",
        "purchase_summary", "gst_summary", "cash_summary", "bank_summary",
        "expenses_summary", "pending_receivables", "pending_payables",
    }

    def _build_response(self, data: Dict[str, Any], user_message: str) -> Dict[str, Any]:
        if data.get("intent") in self._NO_LLM_INTENTS:
            response_text = self._fallback_format(data)
        else:
            response_text = self._explain(data, user_message)
        return {
            "response": response_text,
            "data": data,
            "source": "query_engine",
            "intent": data.get("intent"),
        }

    def _classify_with_learned_patterns(self, message: str) -> Optional[str]:
        if not isinstance(message, str):
            return None
        msg_lower = message.lower().strip()

        if msg_lower in self.learned_patterns:
            entry = self.learned_patterns[msg_lower]
            if isinstance(entry, dict):
                entry["usage_count"] = entry.get("usage_count", 0) + 1
                entry["last_used"] = datetime.utcnow().isoformat()
                return entry.get("intent")

        for pattern, entry in self.learned_patterns.items():
            if isinstance(entry, dict) and len(pattern) > 4 and pattern in msg_lower:
                return entry.get("intent")
        return None

    def _dispatch_with_intent(self, message: str, company_id: int, intent: str) -> Dict[str, Any]:
        try:
            from .query_engine import (
                get_asset_overview, get_pending_maintenance, get_expiring_warranties,
                get_expiring_insurance, get_total_asset_value, get_top_expensive_assets,
                get_assets_above_value, get_unresolved_alerts, get_fuel_cost,
                get_maintenance_cost, get_idle_assets, get_supplier_summary,
                get_asset_depreciation, get_assets_due_for_service, get_dashboard_summary,
                get_gas_cylinder_summary, get_all_assets_detail, get_single_asset_detail,
                get_assets_by_category,
            )
            from .intent_router import (extract_months, extract_days,
                                        extract_vehicle_type, _clean_identifier,
                                        extract_category_from_message)

            dispatch_map = {
                "asset_overview":       lambda: get_asset_overview(company_id),
                "dashboard_summary":    lambda: get_dashboard_summary(company_id),
                "pending_maintenance":  lambda: get_pending_maintenance(company_id),
                "expiring_warranties":  lambda: get_expiring_warranties(company_id, extract_days(message, 30)),
                "expiring_insurance":   lambda: get_expiring_insurance(company_id, extract_days(message, 30)),
                "asset_value":          lambda: get_total_asset_value(company_id),
                "fuel_cost":            lambda: get_fuel_cost(company_id, extract_months(message), extract_vehicle_type(message)),
                "maintenance_cost":     lambda: get_maintenance_cost(company_id, extract_months(message)),
                "gas_cylinder_summary": lambda: get_gas_cylinder_summary(company_id),
                "all_assets_detail":    lambda: get_all_assets_detail(company_id),
                "idle_assets":          lambda: get_idle_assets(company_id),
                "supplier_summary":     lambda: get_supplier_summary(company_id),
                "depreciation":         lambda: get_asset_depreciation(company_id),
                "service_due":          lambda: get_assets_due_for_service(company_id, extract_days(message, 7)),
                "unresolved_alerts":    lambda: get_unresolved_alerts(company_id),
                "category_assets":      lambda: get_assets_by_category(company_id, extract_category_from_message(message) or ""),
                "single_asset_detail":  lambda: get_single_asset_detail(
                    company_id,
                    _clean_identifier(message),
                    category_hint=extract_category_from_message(message)
                ),
            }

            if intent in dispatch_map:
                result = dispatch_map[intent]()
                return result if isinstance(result, dict) else {"intent": None}
            return {"intent": None}

        except Exception as e:
            print(f"[ERROR] _dispatch_with_intent: {e}")
            return {"intent": None}

    def _store_interaction(self, message: str, data: Dict[str, Any], source: str):
        if not isinstance(data, dict):
            return
        self.feedback_cache.append({
            "message":   message,
            "intent":    data.get("intent"),
            "timestamp": datetime.utcnow().isoformat(),
            "success":   data.get("intent") is not None,   # FIX: was data.get("data")
            "source":    source,
        })

    def _update_learned_patterns(self):
        for interaction in self.feedback_cache:
            if not isinstance(interaction, dict):
                continue
            if not (interaction.get("success") and interaction.get("intent")):
                continue
            msg   = interaction.get("message", "").lower().strip()
            intent = interaction.get("intent")
            if not msg or len(msg) < 5:
                continue
            if msg not in self.learned_patterns:
                self.learned_patterns[msg] = {
                    "intent":        intent,
                    "first_learned": datetime.utcnow().isoformat(),
                    "last_used":     datetime.utcnow().isoformat(),
                    "usage_count":   1,
                    "ratings":       [],
                    "avg_rating":    0,
                    "source":        interaction.get("source"),
                }
            elif isinstance(self.learned_patterns[msg], dict):
                self.learned_patterns[msg]["usage_count"] = (
                    self.learned_patterns[msg].get("usage_count", 0) + 1
                )
                self.learned_patterns[msg]["last_used"] = datetime.utcnow().isoformat()
        self._save_learned_patterns()

    def _update_intent_map(self):
        try:
            from .intent_router import INTENT_MAP

            new_patterns: Dict[str, List[str]] = defaultdict(list)
            for interaction in self.feedback_cache:
                if not (isinstance(interaction, dict) and
                        interaction.get("success") and interaction.get("intent")):
                    continue
                for phrase in self._extract_key_phrases(interaction.get("message", "")):
                    new_patterns[interaction["intent"]].append(phrase)

            for intent, phrases in new_patterns.items():
                for i, (keywords, intent_name) in enumerate(INTENT_MAP):
                    if intent_name == intent:
                        new_kw = [p for p in phrases if p not in keywords]
                        if new_kw:
                            INTENT_MAP[i] = (keywords + new_kw, intent_name)
                            print(f"[LEARNING] +{len(new_kw)} keywords for '{intent}'")
                        break

            self._save_intent_updates(INTENT_MAP)
            self.feedback_cache = []
        except Exception as e:
            print(f"[ERROR] _update_intent_map: {e}")

    def _extract_key_phrases(self, message: str) -> List[str]:
        if not isinstance(message, str):
            return []
        stop = {
            "what", "how", "when", "where", "which", "who",
            "is", "are", "the", "a", "an", "of", "for", "to",
            "tell", "me", "about", "show", "please", "want", "know",
            "need", "get", "can", "you", "i", "my", "your",
            "all", "some", "any", "this", "that", "its", "it",
        }
        words = message.lower().split()
        phrases = []
        for j in range(len(words) - 1):
            if words[j] not in stop and words[j + 1] not in stop:
                p = f"{words[j]} {words[j+1]}"
                if len(p) > 4:
                    phrases.append(p)
        return phrases

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_learned_patterns(self):
        try:
            with open(self.learning_file, "w") as f:
                json.dump(self.learned_patterns, f, indent=2)
        except Exception as e:
            print(f"[ERROR] _save_learned_patterns: {e}")

    def _load_learned_patterns(self):
        try:
            with open(self.learning_file, "r") as f:
                data = json.load(f)
            self.learned_patterns = data if isinstance(data, dict) else {}
            print(f"[LEARNING] Loaded {len(self.learned_patterns)} patterns")
        except FileNotFoundError:
            self.learned_patterns = {}
        except Exception as e:
            print(f"[ERROR] _load_learned_patterns: {e}")
            self.learned_patterns = {}

    def _save_intent_updates(self, intent_map):
        try:
            serializable = [
                {"keywords": list(kw), "intent": name, "updated_at": datetime.utcnow().isoformat()}
                for kw, name in intent_map
            ]
            with open(self.intent_map_file, "w") as f:
                json.dump(serializable, f, indent=2)
        except Exception as e:
            print(f"[ERROR] _save_intent_updates: {e}")

    def _load_intent_updates(self):
        try:
            with open(self.intent_map_file, "r") as f:
                updates = json.load(f)
            if not isinstance(updates, list):
                return
            from .intent_router import INTENT_MAP
            for update in updates:
                if not isinstance(update, dict):
                    continue
                for i, (keywords, intent_name) in enumerate(INTENT_MAP):
                    if intent_name == update.get("intent"):
                        merged = list(set(keywords + update.get("keywords", [])))
                        INTENT_MAP[i] = (merged, intent_name)
                        break
            print(f"[LEARNING] Applied {len(updates)} saved intent updates")
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[ERROR] _load_intent_updates: {e}")
