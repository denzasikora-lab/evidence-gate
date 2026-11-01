#!/usr/bin/env python3
"""
Точка входа CLI для навыка find_similar_precedents.
Ищет в графе DataHub прежние артефакты решений и формирует явное сравнение «Что применимо / Что отличается».
"""
import sys
import json
import argparse
from pathlib import Path

# Добавляем корень проекта в sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.api.schemas import ChangeRequest
from src.precedent.retriever import find_precedent_decisions


def main():
    parser = argparse.ArgumentParser(
        description="Найти в графе DataHub прецеденты прежних решений для предложенного изменения."
    )
    parser.add_argument(
        "--urn",
        default="urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details_replica,PROD)",
        help="URN набора данных-кандидата в DataHub",
    )
    parser.add_argument("--old-field", default="order_total", help="Имя существующего поля")
    parser.add_argument("--new-field", default="recognized_revenue", help="Имя предложенного поля")
    parser.add_argument("--change-id", default="cr-precedent-check-002", help="ID изменения")
    parser.add_argument("--pr-url", default="https://github.com/example/repo/pull/105", help="URL запроса на слияние")
    parser.add_argument("--json", action="store_true", help="Вывести исходный JSON результатов поиска прецедентов")
    args = parser.parse_args()

    req = ChangeRequest(
        change_id=args.change_id,
        change_type="field_rename",
        source_asset=args.urn,
        old_field=args.old_field,
        new_field=args.new_field,
        old_type="decimal",
        new_type="decimal",
        pr_url=args.pr_url,
    )

    res = find_precedent_decisions(req)

    if args.json:
        print(json.dumps(res, indent=2))
        return

    print("=" * 80)
    print("НАВЫК: НАЙТИ ПОХОЖИЕ ПРЕЦЕДЕНТЫ — РЕЗУЛЬТАТЫ ПОИСКА")
    print("=" * 80)
    print(f"ID изменения-кандидата: {res['candidate_change_id']}")
    print(f"Целевой актив-кандидат: {res['candidate_source_asset']}")
    print(f"Найдено прецедентов:    {res['precedents_found_count']}")
    print("-" * 80)
    for p in res.get("precedents", []):
        print(f"ID решения-прецедента:  {p['precedent_decision_id']} (прежний результат: {p['prior_status'].upper()})")
        print(f"Прежний целевой актив:  {p['prior_asset_urn']}")
        print(f"Прежний балл риска:     {p['prior_risk_score']}/100")
        print("\nЧто по-прежнему применимо:")
        for item in p["what_still_applies"]:
            print(f"  - {item}")
        print("\nЧто отличается:")
        for item in p["what_differs"]:
            print(f"  - {item}")
        print("\nПовторно использованные доказательства:")
        for item in p["reused_evidence"]:
            print(f"  - {item}")
    print("=" * 80)


if __name__ == "__main__":
    main()
