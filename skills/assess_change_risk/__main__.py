#!/usr/bin/env python3
"""
Точка входа CLI для навыка assess_change_risk.
Оценивает правила риска и проверку метрики для предложенного запроса на изменение схемы.
"""
import sys
import json
import argparse
from pathlib import Path

# Добавляем корень проекта в sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.api.schemas import ChangeRequest
from src.discovery.parser import parse_change_request
from src.evidence.collector import build_evidence_bundle
from src.decision.risk_engine import evaluate_risk
from src.validation.engine import validate_revenue_compatibility
from src.decision.evaluator import build_decision_receipt


def main():
    parser = argparse.ArgumentParser(
        description="Оценить риск и проверить совместимость предложенного изменения схемы."
    )
    parser.add_argument(
        "--fixture",
        help="Путь к JSON-фикстуре ChangeRequest (например, fixtures/net_revenue_rename.json)",
    )
    parser.add_argument(
        "--urn",
        default="urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)",
        help="URN целевого актива в DataHub",
    )
    parser.add_argument("--old-field", default="order_total", help="Имя существующего поля")
    parser.add_argument("--new-field", default="recognized_revenue", help="Имя предложенного поля")
    parser.add_argument("--old-type", default="decimal", help="Существующий тип данных")
    parser.add_argument("--new-type", default="decimal", help="Предложенный тип данных")
    parser.add_argument("--change-id", default="cr-risk-eval-001", help="ID запроса на изменение")
    parser.add_argument("--pr-url", default="https://github.com/example/repo/pull/42", help="URL запроса на слияние")
    parser.add_argument("--json", action="store_true", help="Вывести исходный JSON DecisionReceipt")
    args = parser.parse_args()

    if args.fixture:
        req = parse_change_request(args.fixture)
    else:
        req = ChangeRequest(
            change_id=args.change_id,
            change_type="field_rename",
            source_asset=args.urn,
            old_field=args.old_field,
            new_field=args.new_field,
            old_type=args.old_type,
            new_type=args.new_type,
            pr_url=args.pr_url,
        )

    bundle = build_evidence_bundle(req)
    risk = evaluate_risk(req, bundle)
    val = validate_revenue_compatibility()
    receipt = build_decision_receipt(req, bundle, risk, val)

    if args.json:
        print(json.dumps(receipt.model_dump(), indent=2))
        return

    print("=" * 80)
    print("НАВЫК: ОЦЕНКА РИСКА ИЗМЕНЕНИЯ — СВОДКА")
    print("=" * 80)
    print(f"Целевой актив:          {req.source_asset}")
    print(f"Переименование поля:    '{req.old_field}' -> '{req.new_field}'")
    print(f"URL запроса на слияние: {req.pr_url}")
    print("-" * 80)
    print(f"Балл риска:             {risk.risk_score}/100")
    print(f"Предварительный статус: {risk.leaning.upper()}")
    print(f"Сигналы риска:          {', '.join(risk.signals_triggered)}")
    print(f"Согласующие:            {', '.join(risk.required_approvers)}")
    if risk.unowned_assets_needing_escalation:
        print(f"Активы без владельца:   {', '.join(risk.unowned_assets_needing_escalation)}")
    print("-" * 80)
    print(f"Проверка:               {val.result.upper()}")
    print(f"Прежний агрегат:        ${val.old_aggregate:,.2f}")
    print(f"Предложенный агрегат:   ${val.proposed_aggregate:,.2f}")
    print(f"Дельта:                 {val.delta_pct:.2f}% (допуск: {val.tolerance_pct:.2f}%)")
    print("-" * 80)
    print(f"ИТОГОВОЕ РЕШЕНИЕ: {receipt.status.upper()}")
    print(f"Обоснование:\n  {receipt.business_rationale}")
    print("=" * 80)


if __name__ == "__main__":
    main()
