"""Gemini-powered message composer strictly targeting active Gemini 3 models with persistent retry."""

from __future__ import annotations
import os
import json
import time
import re
import logging
from typing import Any, Dict, List, Optional
from google import genai
from google.genai import types

from core.prompts import (
    COMPOSER_SYSTEM_PROMPT,
    REPLY_SYSTEM_PROMPT,
    build_tick_prompt,
    build_reply_prompt,
)

logger = logging.getLogger("vera-composer")


def _too_similar(a: str, b: str) -> bool:
    wa, wb = set(a.lower().split()), set(b.lower().split())
    if not wa or not wb:
        return False
    return (len(wa & wb) / min(len(wa), len(wb))) > 0.7


def _extract_retry_delay(err_msg: str) -> int:
    match = re.search(r"retry in (\d+(?:\.\d+)?)s", err_msg, re.IGNORECASE)
    if match:
        return int(float(match.group(1))) + 2
    return 10


def _ensure_nonempty_body(data: Dict[str, Any], fallback_body: str) -> Dict[str, Any]:
    if not data.get("body", "").strip():
        data["body"] = fallback_body
    return data


class GeminiComposer:
    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.client = genai.Client(api_key=key) if key else None
        # Only active, supported models in the catalog
        self.models_to_try = ["gemini-3.8-flash", "gemini-3.5-flash"]
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

        data: Optional[Dict[str, Any]] = None

        # Persistent retry: wait out any 503 capacity spikes
        for attempt in range(8):
            for model_name in self.models_to_try:
                try:
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=COMPOSER_SYSTEM_PROMPT,
                            temperature=0.0,
                            response_mime_type="application/json",
                        ),
                    )
                    data = json.loads(response.text)
                    if isinstance(data, dict) and "body" in data:
                        break
                except Exception as e:
                    err_str = str(e)
                    wait_s = _extract_retry_delay(err_str)
                    print(f"[{model_name}] 503 spike or limit. Waiting {wait_s}s (attempt {attempt+1}/8)...")
                    time.sleep(wait_s)
            if data:
                break

        if not data:
            return {
                "body": fallback_msg,
                "cta": "open_ended",
                "template_name": "vera_outbound_v1",
                "template_params": [owner],
                "rationale": "Fallback triggered after API retry.",
            }

        data = _ensure_nonempty_body(data, fallback_msg)
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
        default_reply = "Got it — let me know how you would like to proceed."

        if self.client:
            for model_name in self.models_to_try:
                try:
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=REPLY_SYSTEM_PROMPT,
                            temperature=0.0,
                            response_mime_type="application/json",
                        ),
                    )
                    data = json.loads(response.text)
                    if isinstance(data, dict) and "action" in data:
                        return _ensure_nonempty_body(data, default_reply)
                except Exception:
                    time.sleep(1)

        return {
            "action": "send",
            "body": default_reply,
            "cta": "open_ended",
            "rationale": "Resilient reply fallback.",
        }
