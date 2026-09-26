#!/usr/bin/env python3
"""
magicpin AI Challenge — LLM-Powered Judge Simulator
====================================================
"""
import os
# =============================================================================
# CONFIGURATION
# =============================================================================
BOT_URL = "https://magicpin-vera-bot-4mys.onrender.com"
LLM_PROVIDER = "gemini"
LLM_API_KEY = os.environ.get("GEMINI_API_KEY", "")
LLM_MODEL = "gemini-3.8-flash"
OLLAMA_URL = "http://localhost:11434"
TEST_SCENARIO = "full_evaluation"
# =============================================================================


import sys
import json
import time
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from urllib import request as urlrequest, error as urlerror
from abc import ABC, abstractmethod

TIMEOUT_LLM = 45
DATASET_DIR = Path(__file__).parent / "dataset"

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    MAGENTA = '\033[35m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'

def print_header(text: str):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.RESET}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text.center(70)}{Colors.RESET}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.RESET}\n")

def print_section(text: str):
    print(f"\n{Colors.CYAN}{Colors.BOLD}--- {text} ---{Colors.RESET}\n")

def print_success(text: str):
    print(f"{Colors.GREEN}[PASS]{Colors.RESET} {text}")

def print_fail(text: str):
    print(f"{Colors.RED}[FAIL]{Colors.RESET} {text}")

def print_warn(text: str):
    print(f"{Colors.YELLOW}[WARN]{Colors.RESET} {text}")

def print_info(text: str):
    print(f"{Colors.BLUE}[INFO]{Colors.RESET} {text}")

def print_llm(text: str):
    print(f"{Colors.MAGENTA}[LLM]{Colors.RESET} {text}")

def print_score_bar(dimension: str, score: int, max_score: int = 10):
    bar_filled = int((score / max_score) * 20)
    bar_empty = 20 - bar_filled
    color = Colors.GREEN if score >= 7 else Colors.YELLOW if score >= 4 else Colors.RED
    print(f"  {dimension:22} [{color}{'█' * bar_filled}{Colors.DIM}{'░' * bar_empty}{Colors.RESET}] {color}{score:2}/{max_score}{Colors.RESET}")

def print_reason(text: str):
    wrapped = text[:200] + "..." if len(text) > 200 else text
    print(f"    {Colors.DIM}{wrapped}{Colors.RESET}")

def print_hint(hint: str):
    print(f"\n  {Colors.YELLOW}Hint:{Colors.RESET} {hint}")

@dataclass
class ScoreResult:
    specificity: int = 0
    specificity_reason: str = ""
    category_fit: int = 0
    category_fit_reason: str = ""
    merchant_fit: int = 0
    merchant_fit_reason: str = ""
    decision_quality: int = 0
    decision_quality_reason: str = ""
    engagement_compulsion: int = 0
    engagement_reason: str = ""
    penalties: int = 0
    penalty_reasons: List[str] = field(default_factory=list)
    hint: str = ""

    @property
    def total(self) -> int:
        return max(0, self.specificity + self.category_fit + self.merchant_fit +
                   self.decision_quality + self.engagement_compulsion - self.penalties)

class LLMProvider(ABC):
    @abstractmethod
    def complete(self, prompt: str, system: str = None) -> str:
        pass
    @abstractmethod
    def name(self) -> str:
        pass

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = ""):
        self.api_key = api_key
        self.model = model or "gemini-2.0-flash"

    def name(self) -> str:
        return f"Gemini ({self.model})"

    def complete(self, prompt: str, system: str = None) -> str:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        body = json.dumps({
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1500}
        }).encode("utf-8")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        req = urlrequest.Request(url, data=body, headers={"Content-Type": "application/json"})
        resp = urlrequest.urlopen(req, timeout=TIMEOUT_LLM)
        data = json.loads(resp.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"]

def create_provider() -> LLMProvider:
    return GeminiProvider(LLM_API_KEY, LLM_MODEL)

class DatasetLoader:
    def __init__(self, dataset_dir: Path):
        self.dataset_dir = dataset_dir
        self.categories = {}
        self.merchants = {}
        self.customers = {}
        self.triggers = {}

    def load(self) -> bool:
        try:
            cat_dir = self.dataset_dir / "categories"
            if cat_dir.exists():
                for f in cat_dir.glob("*.json"):
                    data = json.load(open(f, encoding="utf-8"))
                    self.categories[data.get("slug", f.stem)] = data

            for name, container, key in [
                ("merchants_seed.json", "merchants", "merchant_id"),
                ("customers_seed.json", "customers", "customer_id"),
                ("triggers_seed.json", "triggers", "id")
            ]:
                path = self.dataset_dir / name
                if path.exists():
                    data = json.load(open(path, encoding="utf-8"))
                    items = data.get(container, data.get(container.rstrip("s"), []))
                    storage = getattr(self, container)
                    for item in items:
                        if key in item:
                            storage[item[key]] = item
            return True
        except Exception as e:
            print_fail(f"Dataset load error: {e}")
            return False

class BotClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str, timeout: int = 60, body_dict: Dict = None) -> Tuple[Optional[Dict], Optional[str], float]:
        url = f"{self.base_url}{path}"
        start = time.time()
        body = json.dumps(body_dict).encode("utf-8") if body_dict else None
        headers = {"Content-Type": "application/json"}
        req = urlrequest.Request(url, data=body, method=method, headers=headers)
        try:
            resp = urlrequest.urlopen(req, timeout=timeout)
            return json.loads(resp.read().decode("utf-8")), None, (time.time() - start) * 1000
        except urlerror.HTTPError as e:
            latency = (time.time() - start) * 1000
            if e.code == 401:
                return None, "Unauthorized", latency
            try:
                return json.loads(e.read().decode("utf-8")), None, latency
            except:
                return None, f"HTTP {e.code}", latency
        except Exception as e:
            return None, str(e), (time.time() - start) * 1000

    def healthz(self):
        return self._request("GET", "/v1/healthz", 30)

    def metadata(self):
        return self._request("GET", "/v1/metadata", 30)

    def push_context(self, scope, cid, version, payload):
        return self._request("POST", "/v1/context", 30, {
            "scope": scope, "context_id": cid, "version": version,
            "payload": payload, "delivered_at": datetime.now(timezone.utc).isoformat()
        })

    def tick(self, triggers):
        return self._request("POST", "/v1/tick", 45, {
            "now": datetime.now(timezone.utc).isoformat(), "available_triggers": triggers
        })

    def reply(self, conv_id, merchant_id, message, turn):
        return self._request("POST", "/v1/reply", 45, {
            "conversation_id": conv_id, "merchant_id": merchant_id, "customer_id": None,
            "from_role": "merchant", "message": message,
            "received_at": datetime.now(timezone.utc).isoformat(), "turn_number": turn
        })

class LLMScorer:
    SYSTEM = """You are a STRICT judge for the magicpin AI Challenge. You score merchant engagement messages.

SCORING DIMENSIONS (0-10 each):
1. SPECIFICITY: Concrete verifiable facts (numbers, dates, prices, citations).
2. CATEGORY FIT: Vocabulary & tone match the business type.
3. MERCHANT FIT: Personalized to owner name & real data.
4. TRIGGER RELEVANCE: Connects to why messaging right now.
5. ENGAGEMENT COMPULSION: Low friction CTA, clear compulsion lever.

RESPOND ONLY WITH THIS EXACT JSON FORMAT:
{
  "specificity": <0-10>,
  "specificity_reason": "<1-2 sentences>",
  "category_fit": <0-10>,
  "category_fit_reason": "<reason>",
  "merchant_fit": <0-10>,
  "merchant_fit_reason": "<reason>",
  "decision_quality": <0-10>,
  "decision_quality_reason": "<reason>",
  "engagement_compulsion": <0-10>,
  "engagement_reason": "<reason>",
  "hint": "<one sentence guidance>"
}"""

    def __init__(self, llm: LLMProvider, dataset: DatasetLoader):
        self.llm = llm
        self.dataset = dataset

    def score(self, action: Dict, category: Dict, merchant: Dict, trigger: Dict, customer: Dict = None) -> ScoreResult:
        body = action.get("body", "")
        prompt = f"""SCORE THIS MESSAGE:

=== CONTEXT ===
Category: {category.get('slug', 'unknown')}
Merchant: {merchant.get('identity', {}).get('name', 'unknown')}
Owner: {merchant.get('identity', {}).get('owner_first_name', 'unknown')}
Trigger Kind: {trigger.get('kind', 'unknown')}
Trigger Payload: {json.dumps(trigger.get('payload', {}))}

=== BOT MESSAGE ===
Body: "{body}"
CTA: {action.get('cta', 'none')}
Send As: {action.get('send_as', 'vera')}
"""
        try:
            print_llm("Analyzing message...")
            response = self.llm.complete(prompt, self.SYSTEM)
            match = re.search(r'\{[\s\S]*\}', response)
            if match:
                data = json.loads(match.group())
                return ScoreResult(
                    specificity=min(10, max(0, int(data.get("specificity", 5)))),
                    specificity_reason=data.get("specificity_reason", ""),
                    category_fit=min(10, max(0, int(data.get("category_fit", 5)))),
                    category_fit_reason=data.get("category_fit_reason", ""),
                    merchant_fit=min(10, max(0, int(data.get("merchant_fit", 5)))),
                    merchant_fit_reason=data.get("merchant_fit_reason", ""),
                    decision_quality=min(10, max(0, int(data.get("decision_quality", 5)))),
                    decision_quality_reason=data.get("decision_quality_reason", ""),
                    engagement_compulsion=min(10, max(0, int(data.get("engagement_compulsion", 5)))),
                    engagement_reason=data.get("engagement_reason", ""),
                    hint=data.get("hint", "")
                )
        except Exception as e:
            print_warn(f"LLM score parse error: {e}")

        return ScoreResult(specificity=5, category_fit=5, merchant_fit=5, decision_quality=5, engagement_compulsion=5)

class JudgeSimulator:
    def __init__(self, llm: LLMProvider):
        self.llm = llm
        self.client = BotClient(BOT_URL)
        self.dataset = DatasetLoader(DATASET_DIR)
        self.scorer: Optional[LLMScorer] = None

    def run(self, scenario: str) -> bool:
        print_header(f"LLM JUDGE — {scenario.upper()}")
        if not self.dataset.load():
            print_fail("Dataset load failed")
            return False

        # Reset bot state before each local test run so repeated runs don't collide
        self.client._request("POST", "/v1/teardown", 30)

        self.scorer = LLMScorer(self.llm, self.dataset)
        return self._all()

    def _warmup(self) -> bool:
        print_section("WARMUP")
        data, err, lat = self.client.healthz()
        if err:
            print_fail(f"healthz: {err}")
            return False
        print_success(f"healthz ({lat:.0f}ms)")

        data, err, _ = self.client.metadata()
        if not err:
            print_success(f"metadata — Team: {data.get('team_name', '?')}")

        print_section("CONTEXT PUSH")
        for slug, cat in self.dataset.categories.items():
            self.client.push_context("category", slug, 1, cat)
        for mid, m in list(self.dataset.merchants.items())[:5]:
            self.client.push_context("merchant", mid, 1, m)
        print_success("Context pushed successfully")
        return True

    def _auto_reply(self) -> bool:
        print_section("AUTO-REPLY DETECTION")
        mid = list(self.dataset.merchants.keys())[0] if self.dataset.merchants else "m_test"
        auto_msg = "Thank you for contacting us! Our team will respond shortly."
        for i in range(1, 4):
            data, err, _ = self.client.reply(f"conv_auto_{i}", mid, auto_msg, i + 1)
            if err:
                print_fail(f"Reply error: {err}")
                return False
            action = data.get("action", "?")
            if action in ["end", "wait"]:
                print_success(f"Turn {i}: Bot responded with {action.upper()} correctly")
                return True
        return False

    def _intent(self) -> bool:
        print_section("INTENT TRANSITION")
        mid = list(self.dataset.merchants.keys())[0] if self.dataset.merchants else "m_test"
        commitment = "Ok lets do it. Whats next?"
        data, err, _ = self.client.reply("conv_intent_1", mid, commitment, 2)
        if err:
            print_fail(f"Reply error: {err}")
            return False
        # --- DEBUG: always show exactly what the bot returned ---
        print_info(f"merchant_id used for this test: {mid}")
        print_info(f"Raw response from /v1/reply: {json.dumps(data, ensure_ascii=False)}")
        # ---------------------------------------------------------
        body = data.get("body", "").lower()
        if any(w in body for w in ["done", "sending", "draft", "here", "confirm", "proceed"]):
            print_success("Bot correctly switched to ACTION mode")
            return True
        print_fail(f"Bot failed action transition. Full response: {data}")
        return False

    def _hostile(self) -> bool:
        print_section("HOSTILE HANDLING")
        mid = list(self.dataset.merchants.keys())[0] if self.dataset.merchants else "m_test"
        hostile = "Stop messaging me. This is useless spam."
        data, err, _ = self.client.reply("conv_hostile", mid, hostile, 2)
        if err:
            print_fail(f"Reply error: {err}")
            return False
        action = data.get("action")
        if action == "end":
            print_success("Bot correctly ENDED on hostile message")
            return True
        print_fail("Bot did not exit cleanly")
        return False

    def _all(self) -> bool:
        for name, fn in [("warmup", self._warmup), ("auto_reply", self._auto_reply),
                         ("intent", self._intent), ("hostile", self._hostile)]:
            if not fn():
                print_fail(f"Failed scenario: {name}")
                return False
        print_section("ALL SCENARIOS PASSED")
        return True

def main():
    print_header("magicpin AI Challenge — LLM Judge")
    if not LLM_API_KEY or "actual" in LLM_API_KEY:
        print_fail("Set your LLM_API_KEY in judge_simulator.py first!")
        sys.exit(1)
    llm = create_provider()
    judge = JudgeSimulator(llm)
    success = judge.run(TEST_SCENARIO)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()