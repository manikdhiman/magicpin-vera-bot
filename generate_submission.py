"""Generates canonical 30-message submission.jsonl from expanded/test_pairs.json."""

import json
from pathlib import Path
from core.store import ContextStore
from core.composer import GeminiComposer

store = ContextStore()
composer = GeminiComposer()

exp = Path("expanded")
for cat_file in (exp / "categories").glob("*.json"):
    data = json.load(open(cat_file, encoding="utf-8"))
    store.push("category", data["slug"], 1, data)

for m_file in (exp / "merchants").glob("*.json"):
    data = json.load(open(m_file, encoding="utf-8"))
    store.push("merchant", data["merchant_id"], 1, data)

for c_file in (exp / "customers").glob("*.json"):
    data = json.load(open(c_file, encoding="utf-8"))
    store.push("customer", data["customer_id"], 1, data)

for t_file in (exp / "triggers").glob("*.json"):
    data = json.load(open(t_file, encoding="utf-8"))
    store.push("trigger", data["id"], 1, data)

with open(exp / "test_pairs.json", encoding="utf-8") as f:
    pairs = json.load(f)["pairs"]

submission_lines = []
print(f"Composing messages for {len(pairs)} test pairs...")

for p in pairs:
    trg = store.get("trigger", p["trigger_id"])
    merchant = store.get("merchant", p["merchant_id"])
    cat = store.get("category", merchant.get("category_slug")) if merchant else None
    cust = store.get("customer", p.get("customer_id"))

    if not (trg and merchant and cat):
        continue

    composed = composer.compose_tick(cat, merchant, trg, cust)
    send_as = "merchant_on_behalf" if cust else "vera"

    line = {
        "test_id": p["test_id"],
        "trigger_id": p["trigger_id"],
        "merchant_id": p["merchant_id"],
        "customer_id": p.get("customer_id"),
        "send_as": send_as,
        "body": composed.get("body", ""),
        "cta": composed.get("cta", "open_ended"),
        "suppression_key": trg.get("suppression_key", f"{trg['id']}:{p['merchant_id']}"),
        "rationale": composed.get("rationale", ""),
    }
    submission_lines.append(line)
    print(f"[{p['test_id']}] Composed for {merchant.get('identity', {}).get('name')}")

with open("submission.jsonl", "w", encoding="utf-8") as f:
    for item in submission_lines:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

print(f"\nDone! Successfully written {len(submission_lines)} lines to submission.jsonl")
