#!/usr/bin/env python3
"""
Скрипт отправляет запрос ChangeRequest в Evidence Gate.
Может вызвать запущенный API либо выполнить проверку локально.
"""
import sys
import json
import argparse
from pathlib import Path
import urllib.request
import urllib.error

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api.schemas import ChangeRequest
from src.discovery.parser import parse_change_request
from src.evidence.collector import build_evidence_bundle
from src.decision.risk_engine import evaluate_risk
from src.validation.engine import validate_revenue_compatibility
from src.decision.evaluator import build_decision_receipt
from src.writeback.writer import write_decision_provenance


def main():
    parser = argparse.ArgumentParser(description="Отправить запрос на проверку в Evidence Gate.")
    parser.add_argument(
        "--fixture",
        default="fixtures/net_revenue_rename.json",
        help="Путь к JSON-файлу с описанием изменения",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000/evaluate",
        help="Адрес API; можно указать http://127.0.0.1:8000 или полный путь /evaluate",
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON DecisionReceipt")
    args = parser.parse_args()

    req = parse_change_request(args.fixture)
    api_url = args.api_url.rstrip("/")
    if api_url.endswith(":8000") or api_url.endswith("localhost"):
        api_url += "/evaluate"

    print(f"Отправляю изменение «{req.old_field} → {req.new_field}» в Evidence Gate…", flush=True)

    # Try sending to running API first
    payload = json.dumps(req.model_dump()).encode("utf-8")
    request = urllib.request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    receipt_dict = None
    try:
        # Проверка может включать запросы к DataHub и Gemini, поэтому 5 секунд недостаточно.
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status == 200:
                receipt_dict = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"API не ответил ({exc}); выполняю проверку локально…", flush=True)
        # Fallback to direct pipeline execution
        evidence = build_evidence_bundle(req)
        risk = evaluate_risk(req, evidence)
        val = validate_revenue_compatibility()
        receipt = build_decision_receipt(req, evidence, risk, val)
        write_decision_provenance(receipt)
        receipt_dict = receipt.model_dump()

    if args.json:
        print(json.dumps(receipt_dict, indent=2))
        return

    print("=" * 80)
    print("EVIDENCE GATE — CHANGE REQUEST SUBMISSION RESULT")
    print("=" * 80)
    print(f"Change ID:         {receipt_dict.get('decision_id')}")
    print(f"Decision Status:   {receipt_dict.get('status', '').upper()}")
    print(f"Numeric Risk:      {receipt_dict.get('risk_score')}/100")
    print(f"PR / Change URL:   {receipt_dict.get('change_url')}")
    print("-" * 80)
    print(f"Rationale:\n  {receipt_dict.get('business_rationale')}")
    print("-" * 80)
    print(f"Required Approvers:")
    for app in receipt_dict.get("required_approvers", []):
        print(f"  - {app}")
    if receipt_dict.get("unowned_assets_needing_escalation"):
        print("-" * 80)
        print(f"Unowned Assets Needing Escalation:")
        for unowned in receipt_dict.get("unowned_assets_needing_escalation", []):
            print(f"  - {unowned}")
    print("-" * 80)
    print(f"Recommended Action:\n  {receipt_dict.get('recommended_action')}")
    print("=" * 80)


if __name__ == "__main__":
    main()
