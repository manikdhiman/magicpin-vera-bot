"""Finite state machine for WhatsApp / SMS conversation turns."""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Tuple

AUTO_REPLY_PATTERNS = [
    r"thank you for contacting",
    r"thank you for reaching out",
    r"our team will respond shortly",
    r"will get back to you shortly",
    r"we will be back shortly",
    r"automated assistant",
    r"we are currently closed",
    r"thanks for reaching out",
    r"auto-generated",
    r"this is an automated",
    r"we have received your message",
]

# Fix #1: Multi-word phrases to avoid false matches on "stop by" or "monthly report"
HOSTILE_PATTERNS = [
    r"stop messaging",
    r"stop contacting",
    r"stop texting",
    r"\bunsubscribe\b",
    r"useless spam",
    r"do not message",
    r"dont message",
    r"leave me alone",
    r"not interested",
    r"opt out",
    r"\bharass",
]

COMMIT_PATTERNS = [
    r"\byes\b(?!.*\bno\b)",
    r"let'?s do it",
    r"go ahead",
    r"\bconfirm(ed)?\b",
    r"\bproceed\b",
    r"send (the )?draft",
    r"what'?s next",
]

# Fix #2: Removed stray \bca\b pattern, added explicit "chartered accountant"
OFF_TOPIC_PATTERNS = [
    r"\btax(es)?\b",
    r"\bgst\b",
    r"unrelated",
    r"accounting",
    r"filing",
    r"chartered accountant",
]


def is_auto_reply(message: str) -> bool:
    msg = message.lower()
    return any(re.search(pat, msg) for pat in AUTO_REPLY_PATTERNS)


def is_hostile(message: str) -> bool:
    msg = message.lower()
    return any(re.search(pat, msg) for pat in HOSTILE_PATTERNS)


def is_commitment(message: str) -> bool:
    msg = message.lower()
    if re.search(r"\b(not|no|don'?t|never)\b.{0,15}\b(sure|ok|okay|yes)\b", msg):
        return False
    return any(re.search(pat, msg) for pat in COMMIT_PATTERNS)


def is_off_topic(message: str) -> bool:
    msg = message.lower()
    return any(re.search(pat, msg) for pat in OFF_TOPIC_PATTERNS)


def evaluate_reply_state(
    history: List[Dict[str, Any]],
    current_message: str,
    turn_number: int,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Evaluate reply state deterministically before calling LLM."""
    clean_msg = current_message.strip()

    if is_hostile(clean_msg):
        return "hostile", {
            "action": "end",
            "body": "Understood. I will not message you again regarding this.",
            "cta": "none",
            "rationale": "Merchant opted out or expressed hostility.",
        }

    inbound_msgs = [
        t["msg"].strip().lower()
        for t in history
        if t.get("from") in ("merchant", "customer")
    ]
    if len(inbound_msgs) >= 2 and inbound_msgs[-1] == inbound_msgs[-2]:
        return "duplicate_auto_reply", {
            "action": "wait",
            "wait_seconds": 3600,
            "rationale": "Consecutive identical inbound messages detected; avoiding reply loop.",
        }

    if is_auto_reply(clean_msg):
        return "auto_reply", {
            "action": "wait",
            "wait_seconds": 3600,
            "rationale": "Automated responder detected; waiting for human owner.",
        }

    if is_commitment(clean_msg):
        return "commit", None

    if is_off_topic(clean_msg):
        return "off_topic", None

    if turn_number > 6:
        return "exhausted", {
            "action": "end",
            "body": "Thank you! Feel free to reach back out anytime when you would like to revisit this.",
            "cta": "none",
            "rationale": "Max conversation turns reached cleanly.",
        }

    return "continue", None