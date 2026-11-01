#!/usr/bin/env python3
"""
Точка входа CLI для навыка create_decision_provenance.
Записывает структурированные свойства Decision Provenance, ссылки на документацию и операционные инциденты в GMS DataHub.
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
from src.writeback.writer import write_decision_provenance


def main():
    parser = argparse.ArgumentParser(
        description="Записать артефакт метаданных Decision Provenance обратно в GMS DataHub."
    )
    parser.add_argument(
        "--fixture",
        default="fixtures/net_revenue_rename.json",
        help="Путь к JSON-фикстуре ChangeRequest",
    )
    parser.add_argument("--json", action="store_true", help="Вывести исходный JSON результата записи")
    args = parser.parse_args()

    req = parse_change_request(args.fixture)
    bundle = build_evidence_bundle(req)
    risk = evaluate_risk(req, bundle)
    val = validate_revenue_compatibility()
    receipt = build_decision_receipt(req, bundle, risk, val)

    res = write_decision_provenance(receipt)

    if args.json:
        print(json.dumps(res, indent=2))
        return

    print("=" * 80)
    print("НАВЫК: СОЗДАТЬ ОБОСНОВАНИЕ РЕШЕНИЯ — ЗАПИСЬ ВЫПОЛНЕНА")
    print("=" * 80)
    print(f"URN целевого актива:               {res['asset_urn']}")
    print(f"ID решения:                         {res['decision_id']}")
    print(f"Статус решения:                     {res['status'].upper()}")
    print(f"Записано пользовательских свойств:  {res['custom_properties_emitted']}")
    print(f"Ссылка на документацию:             {res['documentation_link']}")
    print(f"URN нативного инцидента:            {res['incident_urn']}")
    print("=" * 80)


if __name__ == "__main__":
    main()
