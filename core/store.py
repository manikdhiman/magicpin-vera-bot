"""In-memory ContextStore supporting versioning, replacement, and conversations."""

from __future__ import annotations
from typing import Any, Dict, Optional, Set, Tuple


class ContextStore:
    def __init__(self) -> None:
        # Key: (scope, context_id) -> {"version": int, "payload": dict}
        self.contexts: Dict[Tuple[str, str], Dict[str, Any]] = {}
        # Key: conversation_id -> list of turn dicts
        self.conversations: Dict[str, list[Dict[str, Any]]] = {}
        # Tracks suppression keys used during ticks
        self.sent_suppression_keys: Set[str] = set()

    def push(
        self, scope: str, context_id: str, version: int, payload: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Store a context payload.
        Returns:
            (accepted, error_reason, current_version)
        """
        key = (scope, context_id)
        current = self.contexts.get(key)
        if current is not None and current["version"] >= version:
            return False, "stale_version", current["version"]

        self.contexts[key] = {"version": version, "payload": payload}
        return True, None, None

    def get(self, scope: str, context_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not context_id:
            return None
        item = self.contexts.get((scope, context_id))
        return item["payload"] if item else None

    def count_by_scope(self) -> Dict[str, int]:
        counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        for (scope, _), _ in self.contexts.items():
            if scope in counts:
                counts[scope] += 1
        return counts

    def record_turn(
        self, conversation_id: str, from_role: str, message: str
    ) -> list[Dict[str, Any]]:
        history = self.conversations.setdefault(conversation_id, [])
        history.append({"from": from_role, "msg": message})
        return history

    def get_history(self, conversation_id: str) -> list[Dict[str, Any]]:
        return self.conversations.get(conversation_id, [])