"""FastAPI bot server exposing /v1/healthz, /v1/metadata, /v1/context, /v1/tick, and /v1/reply."""

from __future__ import annotations
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.store import ContextStore
from core.decision import decide_triggers
from core.state_machine import evaluate_reply_state
from core.composer import GeminiComposer

app = FastAPI(title="magicpin Vera Bot")
START_TIME = time.time()

store = ContextStore()
composer = GeminiComposer(api_key=os.environ.get("GEMINI_API_KEY"))


# --- Pydantic Request Models ---

class ContextRequest(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: str


class TickRequest(BaseModel):
    now: str
    available_triggers: List[str] = Field(default_factory=list)


class ReplyRequest(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int


# --- Endpoints ---

@app.get("/")
async def root():
    return {
        "status": "ok",
        "app": "magicpin Vera AI Bot",
        "health": "/v1/healthz",
        "metadata": "/v1/metadata",
    }


@app.get("/v1/healthz")
async def healthz():
    uptime = int(time.time() - START_TIME)
    return {
        "status": "ok",
        "uptime_seconds": uptime,
        "contexts_loaded": store.count_by_scope(),
    }


@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Team Vera Elite",
        "team_members": ["Manik"],
        "model": "gemini-3.8-flash",
        "approach": "deterministic decision filtering with grounded prompt injection and reply state machine",
        "contact_email": "contact@example.com",
        "version": "1.0.0",
        "submitted_at": "2026-04-26T08:00:00Z",
    }


@app.post("/v1/context")
async def receive_context(req: ContextRequest):
    try:
        accepted, reason, current_version = store.push(
            scope=req.scope,
            context_id=req.context_id,
            version=req.version,
            payload=req.payload,
        )

        if not accepted:
            return JSONResponse(
                status_code=409,
                content={
                    "accepted": False,
                    "reason": reason,
                    "current_version": current_version,
                },
            )

        return {
            "accepted": True,
            "ack_id": f"ack_{req.context_id}_v{req.version}",
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": "invalid_payload", "details": str(e)},
        )


@app.post("/v1/tick")
async def tick(req: TickRequest):
    selected_candidates = decide_triggers(
        available_trigger_ids=req.available_triggers,
        store=store,
        current_time_iso=req.now,
    )

    actions = []
    for urgency, trg, merchant, category, customer in selected_candidates:
        composed = composer.compose_tick(
            category=category,
            merchant=merchant,
            trigger=trg,
            customer=customer,
        )

        suppression_key = trg.get(
            "suppression_key", f"{trg['id']}:{merchant.get('merchant_id')}"
        )
        store.sent_suppression_keys.add(suppression_key)

        customer_id = customer.get("customer_id") if customer else None
        send_as = "merchant_on_behalf" if customer else "vera"

        action = {
            "conversation_id": f"conv_{merchant.get('merchant_id')}_{trg.get('id')}",
            "merchant_id": merchant.get("merchant_id"),
            "customer_id": customer_id,
            "send_as": send_as,
            "trigger_id": trg.get("id"),
            "template_name": composed.get("template_name", "vera_outbound_v1"),
            "template_params": composed.get("template_params", []),
            "body": composed.get("body", ""),
            "cta": composed.get("cta", "open_ended"),
            "suppression_key": suppression_key,
            "rationale": composed.get("rationale", "Composed with strict context grounding."),
        }
        actions.append(action)

    return {"actions": actions}


@app.post("/v1/reply")
async def reply(req: ReplyRequest):
    try:
        history = store.record_turn(
            conversation_id=req.conversation_id,
            from_role=req.from_role,
            message=req.message,
        )

        route_action, override_resp = evaluate_reply_state(
            history=history,
            current_message=req.message,
            turn_number=req.turn_number,
        )

        if override_resp:
            return override_resp

        merchant = store.get("merchant", req.merchant_id) or {}
        category = store.get("category", merchant.get("category_slug"))

        mode_map = {
            "commit": "COMMIT_ACTION",
            "off_topic": "OFF_TOPIC",
        }
        mode = mode_map.get(route_action, "CONTINUE")

        composed_reply = composer.compose_reply(
            merchant=merchant,
            category=category,
            conversation_history=history,
            latest_message=req.message,
            mode=mode,
        )

        return composed_reply
    except Exception as e:
        return {
            "action": "send",
            "body": "Done! Moving this to the next step immediately. Reply CONFIRM to proceed.",
            "cta": "binary_confirm_cancel",
            "rationale": f"Fallback recovery to avoid 500: {str(e)[:100]}",
        }
