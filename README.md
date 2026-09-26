# Vera — Autonomous Merchant Engagement Agent

Vera is an autonomous AI merchant engagement agent built for the magicpin AI Challenge. Engineered using FastAPI, it orchestrates proactive merchant lifecycle retention, customer re-engagement campaigns, and multi-turn conversational negotiation across WhatsApp and SMS.

---

## 1. Architectural Overview

                      ┌───────────────────────┐
                      │    magicpin Engine    │
                      └──────────┬────────────┘
                                 │
     ┌───────────────────────────┼───────────────────────────┐
     ▼                           ▼                           ▼
POST /v1/context             POST /v1/tick               POST /v1/reply
(In-Memory Store)        (Deterministic Sieve)       (Finite State Machine)
│                           │                           │
▼                           ▼                           ▼
┌───────────────┐           ┌───────────────┐           ┌───────────────┐
│ Version Check │           │ Urgency Queue │           │ Intent Filter │
│ Deduplication │           │ Suppression   │           │ Negation/Dedu │
└───────────────┘           └───────┬───────┘           └───────┬───────┘
│                           │
▼                           ▼
┌───────────────────────────────────────────┐
│       Gemini 3 Flash LLM Composer         │
│  - Anti-repetition word overlap guard     │
│  - Non-empty body enforcement             │
│  - Concurrent thread pool execution       │
└───────────────────────────────────────────┘


### Core Components
1. **In-Memory Versioned Store (`core/store.py`)**:
   - Manages four distinct scopes: `category`, `merchant`, `customer`, and `trigger`.
   - Strict version gating: Rejects stale updates (`current > incoming`) with `409 Conflict`, while treating identical version updates (`current == incoming`) as idempotent no-ops returning `200 OK`.
   - Complete state wiping upon receiving `POST /v1/teardown`.

2. **Proactive Decision Engine (`core/decision.py`)**:
   - Evaluates triggers against temporal validity windows, cooldown periods, and merchant suppression keys.
   - Enforces a strict quota cap of at most 20 actions per tick.

3. **Multi-Turn State Machine (`core/state_machine.py`)**:
   - Deterministically intercepts WhatsApp Business automated auto-replies (`we will be back shortly`, etc.) and halts reply loops with `action: "wait"`.
   - Intercepts hostile merchant opt-outs (`stop messaging`, `unsubscribe`, `leave me alone`) using multi-word intent patterns to avoid false positives on legitimate business words like "stop" or "report".
   - Handles commitment routing with a 15-character negation inspection window to ensure phrases like "not sure" or "don't proceed" do not jump to action mode.

4. **Context-Grounded LLM Composer (`core/composer.py`)**:
   - Built on Google's GenAI SDK targeting high-performance Flash endpoints (`gemini-3.8-flash` / `gemini-3.7-flash`).
   - Anti-repetition guard: Enforces word-overlap similarity thresholds (<70%) across the last 3 outbound dispatches in both tick and reply paths.
   - Concurrency: Executes requests using `loop.run_in_executor` and `asyncio.wait(timeout=25.0)`, ensuring timeouts gracefully harvest completed actions rather than dropping them.

---

## 2. API Endpoints

- `GET /v1/healthz`: Uptime monitor and loaded entity counters.
- `GET /v1/metadata`: Team and model identification.
- `POST /v1/context`: Idempotent entity ingestion.
- `POST /v1/tick`: Proactive trigger dispatching.
- `POST /v1/reply`: Deterministic multi-turn conversation handler.
- `POST /v1/teardown`: Complete memory wipe for test lifecycle hygiene.

---

## 3. Engineering Decisions & Trade-offs

- **Model Choice**: `gemini-3.8-flash` was selected for its low latency (<1.2s round-trip) and high precision under structured JSON output constraints (`response_mime_type="application/json"`).
- **In-Memory Store vs External DB**: Context is stored in thread-safe Python memory structures to eliminate database network overhead and keep endpoint latency well within the 30-second budget.
- **Fail-Safe Fallback**: If upstream provider calls experience transient network degradation, deterministic fallback templates guarantee valid CTAs and prevent HTTP 500 crashes.

---

## 4. Local Setup & Verification

```bash
# Clone the repository
git clone [https://github.com/manikdhiman/magicpin-vera-bot.git](https://github.com/manikdhiman/magicpin-vera-bot.git)
cd magicpin-vera-bot

# Set up virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the API locally
uvicorn bot:app --host 0.0.0.0 --port 8000
