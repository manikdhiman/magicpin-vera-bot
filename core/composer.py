"""Gemini-powered deterministic message composer with retry, fallback, anti-repetition, and empty-body guards."""

from __future__ import annotations
import os
import json
import time
import logging
from typing import Any, Dict, List, Optional
from google import genai
from google.genai import types

logger = logging.getLogger("vera.composer")

from core.prompts import (
    COMPOSER_SYSTEM_PROMPT,
    REPLY_SYSTEM_PROMPT,
    build_tick_prompt,
    build_reply_prompt,
)


def _too_similar(a: str, b: str) -> bool:
    """Cheap overlap check: shares >70% of words with a prior message."""
    wa, wb = set(a.lower().split()), set(b.lower().split())
    if not wa or not wb:
        return False
    overlap = len(wa & wb) / min(len(wa), len(wb))
    return overlap > 0.7


def _ensure_nonempty_body(data: Dict[str, Any], fallback_body: str) -> Dict[str, Any]:
    """Guard against empty/whitespace body causing -2 penalties."""
    if not data.get("body", "").strip():
        data["body"] = fallback_body
    return data


class GeminiComposer:
    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.client = genai.Client(api_key=key) if key else None
        self.model = "gemini-3.8-flash"
        self._sent_cache: Dict[str, List[str]] = {}

    def compose_tick(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        prompt = build_tick_prompt(category, merchant, trigger, customer)
        owner = merchant.get("identity", {}).get("owner_first_name", "there")
        m_id = merchant.get("merchant_id", "unknown")
        fallback_msg = f"Hi {owner}, checking in regarding updates for {merchant.get('identity', {}).get('name', 'your listing')}."

        if not self.client:
            return {
                "body": fallback_msg,
                "cta": "open_ended",
                "template_name": "vera_generic_v1",
                "template_params": [owner],
                "rationale": "Fallback composition without LLM key.",
            }

        recent_bodies = self._sent_cache.get(m_id, [])
        if recent_bodies:
            prompt += f"\n\nCRITICAL ANTI-REPETITION CONSTRAINT: Do not repeat this recent wording sent to this merchant: '{recent_bodies[-1]}'"

        data: Optional[Dict[str, Any]] = None
        for attempt in range(3):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=COMPOSER_SYSTEM_PROMPT,
                        temperature=0.0,
                        response_mime_type="application/json",
                    ),
                )
                data = json.loads(response.text)
                break
            except Exception as e:
                logger.error(f"compose_tick Gemini call failed (attempt {attempt+1}/3) for merchant={m_id}: {e!r}")
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))

        if not data:
            return {
                "body": fallback_msg,
                "cta": "open_ended",
                "template_name": "vera_outbound_v1",
                "template_params": [owner],
                "rationale": "Fallback triggered after API retry.",
            }

        # Check overlap against last 3 proactive dispatches for this merchant
        body = data.get("body", "")
        if body and any(_too_similar(body, prev) for prev in recent_bodies[-3:]):
            retry_prompt = (
                prompt
                + f"\n\nYour previous draft was too similar to a recent message. Rewrite with completely different phrasing and perspective: '{body}'"
            )
            try:
                retry_response = self.client.models.generate_content(
                    model=self.model,
                    contents=retry_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=COMPOSER_SYSTEM_PROMPT,
                        temperature=0.3,
                        response_mime_type="application/json",
                    ),
                )
                data = json.loads(retry_response.text)
            except Exception as e:
                logger.error(f"compose_tick anti-repetition retry failed for merchant={m_id}: {e!r}")

        data = _ensure_nonempty_body(data, fallback_msg)
        body = data.get("body", "")

        if body:
            if m_id not in self._sent_cache:
                self._sent_cache[m_id] = []
            self._sent_cache[m_id].append(body)

        return data

    def compose_reply(
        self,
        merchant: Dict[str, Any],
        category: Optional[Dict[str, Any]],
        conversation_history: list[Dict[str, Any]],
        latest_message: str,
        mode: str = "CONTINUE",
    ) -> Dict[str, Any]:
        prompt = build_reply_prompt(
            merchant, category, conversation_history, latest_message, mode
        )
        prior_vera_bodies = [t["msg"] for t in conversation_history if t.get("from") == "vera"]
        default_reply = "Got it — let me know how you would like to proceed."

        if self.client:
            for attempt in range(3):
                try:
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=REPLY_SYSTEM_PROMPT,
                            temperature=0.0,
                            response_mime_type="application/json",
                        ),
                    )
                    data = json.loads(response.text)
                    if isinstance(data, dict) and "action" in data:
                        body = data.get("body", "")
                        # Fix #3: Check in-conversation duplicate against prior Vera turns
                        if body and any(_too_similar(body, prev) for prev in prior_vera_bodies[-3:]):
                            retry_prompt = prompt + (
                                f"\n\nYour previous draft repeated earlier phrasing in this "
                                f"conversation: '{body}'. Rewrite with a genuinely different "
                                f"angle and wording."
                            )
                            try:
                                retry_resp = self.client.models.generate_content(
                                    model=self.model,
                                    contents=retry_prompt,
                                    config=types.GenerateContentConfig(
                                        system_instruction=REPLY_SYSTEM_PROMPT,
                                        temperature=0.3,
                                        response_mime_type="application/json",
                                    ),
                                )
                                retry_data = json.loads(retry_resp.text)
                                if isinstance(retry_data, dict) and retry_data.get("body"):
                                    return _ensure_nonempty_body(retry_data, default_reply)
                            except Exception as e:
                                logger.error(f"compose_reply anti-repetition retry failed for mode={mode}: {e!r}")

                        return _ensure_nonempty_body(data, default_reply)
                except Exception as e:
                    logger.error(f"compose_reply Gemini call failed (attempt {attempt+1}/3) for mode={mode}: {e!r}")
                    if attempt < 2:
                        time.sleep(1.5 * (attempt + 1))

        # Fallback branches
        if mode == "COMMIT_ACTION":
            return {
                "action": "send",
                "body": "Done! I have prepared the draft and next steps right here. Reply CONFIRM to proceed immediately.",
                "cta": "binary_confirm_cancel",
                "rationale": "Switched cleanly to action mode upon merchant commitment.",
            }
        elif mode == "OFF_TOPIC":
            return {
                "action": "send",
                "body": "I will leave tax filing to your accountant as that is outside my scope, but let's continue with your listing update.",
                "cta": "open_ended",
                "rationale": "Politely redirected off-topic inquiry back to campaign scope.",
            }

        return {
            "action": "send",
            "body": "Understood! Moving this forward to the next step.",
            "cta": "open_ended",
            "rationale": "Resilient reply fallback.",
        }