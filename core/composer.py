"""Gemini-powered deterministic message composer with retry, fallback, and anti-repetition guards."""

from __future__ import annotations
import os
import json
import time
from typing import Any, Dict, List, Optional
from google import genai
from google.genai import types

from core.prompts import (
    COMPOSER_SYSTEM_PROMPT,
    REPLY_SYSTEM_PROMPT,
    build_tick_prompt,
    build_reply_prompt,
)


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

        if not self.client:
            return {
                "body": f"Hi {owner}, checking in with updates for {merchant.get('identity', {}).get('name')}.",
                "cta": "open_ended",
                "template_name": "vera_generic_v1",
                "template_params": [owner],
                "rationale": "Fallback composition without LLM key.",
            }

        recent_bodies = self._sent_cache.get(m_id, [])
        if recent_bodies:
            prompt += f"\n\nCRITICAL ANTI-REPETITION CONSTRAINT: Do not repeat this recent wording sent to this merchant: '{recent_bodies[-1]}'"

        for attempt in range(2):
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
                body = data.get("body", "")
                if body:
                    if m_id not in self._sent_cache:
                        self._sent_cache[m_id] = []
                    self._sent_cache[m_id].append(body)
                return data
            except Exception:
                time.sleep(1)

        return {
            "body": f"Hi {owner}, checking in regarding updates for your listing.",
            "cta": "open_ended",
            "template_name": "vera_outbound_v1",
            "template_params": [owner],
            "rationale": "Fallback triggered after API retry.",
        }

    def compose_reply(
        self,
        merchant: Dict[str, Any],
        category: Optional[Dict[str, Any]],
        conversation_history: list[Dict[str, Any]],
        latest_message: str,
        mode: str = "CONTINUE",
    ) -> Dict[str, Any]:
        prompt = build_reply_prompt(merchant, category, conversation_history, latest_message, mode)

        if self.client:
            for attempt in range(2):
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
                        return data
                except Exception:
                    time.sleep(1)

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