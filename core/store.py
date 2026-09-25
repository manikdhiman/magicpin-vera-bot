"""In-memory versioned context store."""

from __future__ import annotations
from typing import Any, Dict, Optional, Tuple, Set


class ContextStore:
    def __init__(self):
        self.categories: Dict[str, Dict[str, Any]] = {}
        self.merchants: Dict[str, Dict[str, Any]] = {}
        self.customers: Dict[str, Dict[str, Any]] = {}
        self.triggers: Dict[str, Dict[str, Any]] = {}
        self.sent_suppression_keys: Set[str] = set()
        self.conversations: Dict[str, list[Dict[str, Any]]] = {}

    def _get_target_map(self, scope: str) -> Optional[Dict[str, Dict[str, Any]]]:
        mapping = {
            "category": self.categories,
            "merchant": self.merchants,
            "customer": self.customers,
            "trigger": self.triggers,
        }
        return mapping.get(scope)

    def push(
        self, scope: str, context_id: str, version: int, payload: Dict[str, Any]
    ) -> Tuple[bool, str, int]:
        target_map = self._get_target_map(scope)
        if target_map is None:
            return False, "invalid_scope", 0

        current = target_map.get(context_id)

        if current is not None:
            if current["version"] == version:
                return True, "noop_same_version", current["version"]
            if current["version"] > version:
                return False, "stale_version", current["version"]

        target_map[context_id] = {
            "version": version,
            "payload": payload,
        }
        return True, "stored", version

    def get(self, scope: str, context_id: str) -> Optional[Dict[str, Any]]:
        target_map = self._get_target_map(scope)
        if target_map is None:
            return None
        entry = target_map.get(context_id)
        return entry["payload"] if entry else None

    def count_by_scope(self) -> Dict[str, int]:
        return {
            "category": len(self.categories),
            "merchant": len(self.merchants),
            "customer": len(self.customers),
            "trigger": len(self.triggers),
        }

    def record_turn(self, conversation_id: str, from_role: str, message: str) -> list[Dict[str, Any]]:
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = []
        self.conversations[conversation_id].append({
            "from": from_role,
            "msg": message,
        })
        return self.conversations[conversation_id]