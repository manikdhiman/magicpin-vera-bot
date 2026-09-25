"""Deterministic state machine handling multi-turn replays, auto-replies, and hostility."""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Tuple


AUTO_REPLY_PATTERNS = [
    r"thank you for contacting",
    r"our team will respond shortly",
    r"automated assistant",
    r"we are currently closed",
    r"thanks for reaching out",
    r"auto-generated",
    r"we have received your message",
]

HOSTILE_PATTERNS = [
    r"stop messaging",
    r"useless spam",
    r"not interested",
    r"don't message",
    r"dont message",
    r"why are you bothering",
    r"opt out",
    r"unsubscribe",
    r"fraud",
    r"harass",
]

COMMIT_PATTERNS = [
    r"\byes\b",
    r"\bya\b",
    r"let'?s do it",
    r"go ahead",
    r"send (the )?abstract",
    r"draft",
    r"confirm",
    r"proceed",
    r"whats next",
    r"what'?s next",
    r"sure",
    r"ok",
    r"okay",
]

OFF_TOPIC_PATTERNS = [
    r"gst filing",
    r"tax return",
    r"itr",
    r"income tax",
    r"loan",
]


def is_auto_reply(message: str) -> bool:
    msg = message.lower()
    return any(re.search(pat, msg) for pat in AUTO_REPLY_PATTERNS)


def is_hostile(message: str) -> bool:
    msg = message.lower()
    return any(re.search(pat, msg) for pat in HOSTILE_PATTERNS)


def is_commitment(message: str) -> bool:
    msg = message.lower()
    return any(re.search(pat, msg) for pat in COMMIT_PATTERNS)


def is_off_topic(message: str) -> bool:
    msg = message.lower()
    return any(re.search(pat, msg) for pat in OFF_TOPIC_PATTERNS)


def evaluate_reply_state(
    history: List[Dict[str, Any]],
    current_message: str,
    turn_number: int,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Evaluates incoming merchant/customer message.
    Returns:
        (route_action, override_response_dict)
        where route_action is one of: "end", "wait", "off_topic", "commit", "continue"
    """
    # 1. Check hostility / explicit opt-out
    if is_hostile(current_message):
        return "end", {
            "action": "end",
            "rationale": "Merchant explicitly requested to stop messaging; exiting politely and suppressing future triggers.",
        }

    # 2. Check auto-reply loop
    # Inspect inbound messages from merchant
    inbound_msgs = [t["msg"].strip().lower() for t in history if t.get("from") == "merchant"]
    
    # Check if the last 2+ incoming messages are identical
    if len(inbound_msgs) >= 2 and inbound_msgs[-1] == inbound_msgs[-2]:
        if len(inbound_msgs) >= 3 and inbound_msgs[-1] == inbound_msgs[-3]:
            return "end", {
                "action": "end",
                "rationale": "Detected repeated identical auto-replies 3+ times; concluding conversation to avoid spam.",
            }
        return "wait", {
            "action": "wait",
            "wait_seconds": 86400,
            "rationale": "Same auto-reply detected twice in a row; backing off 24 hours.",
        }

    if is_auto_reply(current_message):
        if turn_number <= 2:
            return "wait", {
                "action": "wait",
                "wait_seconds": 14400,
                "rationale": "Detected canned WhatsApp Business auto-reply; backing off 4 hours for human owner.",
            }
        return "end", {
            "action": "end",
            "rationale": "Continuous auto-reply with no human engagement; ending conversation.",
        }

    # 3. Off-topic redirection check
    if is_off_topic(current_message):
        return "off_topic", None

    # 4. Intent commit check
    if is_commitment(current_message):
        return "commit", None

    return "continue", None