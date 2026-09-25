"""Deterministic decision layer for ranking, suppression, and trigger filtering."""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from core.store import ContextStore


def _parse_iso(iso_str: str) -> datetime:
    normalized = iso_str.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def decide_triggers(
    available_trigger_ids: List[str],
    store: ContextStore,
    current_time_iso: str,
) -> List[Tuple[int, Dict[str, Any], Dict[str, Any], Dict[str, Any], Any]]:
    """
    Ranks, filters, and resolves candidate triggers.
    Returns:
        List of tuples: (urgency, trigger, merchant, category, customer)
    """
    candidates = []
    now_dt = _parse_iso(current_time_iso)

    for tid in available_trigger_ids:
        trg = store.get("trigger", tid)
        if not trg:
            continue

        # Check expiration
        expires_at = trg.get("expires_at")
        if expires_at:
            try:
                exp_dt = _parse_iso(expires_at)
                if exp_dt < now_dt:
                    continue
            except Exception:
                pass

        # Check suppression
        suppression_key = trg.get("suppression_key")
        if suppression_key and suppression_key in store.sent_suppression_keys:
            continue

        merchant_id = trg.get("merchant_id")
        merchant = store.get("merchant", merchant_id)
        if not merchant:
            continue

        category_slug = merchant.get("category_slug")
        category = store.get("category", category_slug)
        if not category:
            continue

        customer_id = trg.get("customer_id")
        customer = store.get("customer", customer_id) if customer_id else None

        urgency = trg.get("urgency", 1)
        candidates.append((urgency, trg, merchant, category, customer))

    # Sort descending by urgency (5 -> 1)
    candidates.sort(key=lambda x: -x[0])

    # Enforce hard cap of 20 proactive sends per tick
    return candidates[:20]