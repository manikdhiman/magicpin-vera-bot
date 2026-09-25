"""Gemini-powered deterministic message composer."""

from __future__ import annotations
import os
import json
from typing import Any, Dict, Optional
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

    def compose_tick(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Compose proactive initial message for /v1/tick."""
        prompt = build_tick_prompt(category, merchant, trigger, customer)

        if not self.client:
            # Fallback for testing when no API key is set
            owner = merchant.get("identity", {}).get("owner_first_name", "there")
            return {
                "body": f"Hi {owner}, checking in with updates for {merchant.get('identity', {}).get('name')}.",
                "cta": "open_ended",
                "template_name": "vera_generic_v1",
                "template_params": [owner],
                "rationale": "Fallback composition without LLM key.",
            }

        response = self.client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=COMPOSER_SYSTEM_PROMPT,
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )

        try:
            return json.loads(response.text)
        except Exception:
            text = response.text or ""
            return {
                "body": text.strip(),
                "cta": "open_ended",
                "template_name": "vera_outbound_v1",
                "template_params": [],
                "rationale": "Raw parsed model output",
            }

    def compose_reply(
        self,
        merchant: Dict[str, Any],
        category: Optional[Dict[str, Any]],
        conversation_history: list[Dict[str, Any]],
        latest_message: str,
        mode: str = "CONTINUE",
    ) -> Dict[str, Any]:
        """Compose dynamic multi-turn response for /v1/reply."""
        prompt = build_reply_prompt(merchant, category, conversation_history, latest_message, mode)

        if not self.client:
            return {
                "action": "send",
                "body": "Got it, moving this forward right away.",
                "cta": "open_ended",
                "rationale": "Fallback reply without LLM key.",
            }

        response = self.client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=REPLY_SYSTEM_PROMPT,
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )

        try:
            return json.loads(response.text)
        except Exception:
            return {
                "action": "send",
                "body": response.text.strip(),
                "cta": "open_ended",
                "rationale": "Model generated reply",
            }