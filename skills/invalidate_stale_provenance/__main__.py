#!/usr/bin/env python3
"""
Точка входа CLI для навыка invalidate_stale_provenance.
Сравнивает рабочие метаданные графа DataHub с сохранёнными снимками Decision Provenance и обновляет статус до 'stale' в GMS DataHub при изменении зависимостей.
"""
import sys
import json
import argparse
from pathlib import Path

# Добавляем корень проекта в sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.invalidation.watcher import (
    simulate_graph_change,
    check_and_invalidate_provenance,
    restore_glossary_terms,
)


def main():
    parser = argparse.ArgumentParser(
        description="Проверить граф DataHub и сделать устаревшими артефакты Decision Provenance."
    )
    parser.add_argument(
        "--urn",
        default="urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)",
        help="URN целевого набора данных в DataHub",
    )
    parser.add_argument(
        "--simulate-remove-glossary",
        action="store_true",
        help="Имитировать реальное изменение графа (удалить термин глоссария дохода) перед проверкой",
    )
    parser.add_argument(
        "--restore-terms",
        action="store_true",
        help="Восстановить в DataHub исходные термины глоссария набора данных",
    )
    parser.add_argument("--json", action="store_true", help="Вывести исходный JSON-результат")
    args = parser.parse_args()

    if args.restore_terms:
        restore_glossary_terms(args.urn)
        print(f"Исходные термины глоссария восстановлены для актива: {args.urn}")
        return

    if args.simulate_remove_glossary:
        sim_res = simulate_graph_change(args.urn, action="remove_glossary_term")
        print(f"[Имитированное изменение графа] Удалён термин: {sim_res['removed_term_urn']}")

    res = check_and_invalidate_provenance(args.urn)

    if args.json:
        print(json.dumps(res, indent=2))
        return

    print("=" * 80)
    print("НАВЫК: ИНВАЛИДИРОВАТЬ УСТАРЕВШЕЕ ОБОСНОВАНИЕ — ОТЧЁТ НАБЛЮДАТЕЛЯ")
    print("=" * 80)
    print(f"URN целевого актива:    {res.get('asset_urn')}")
    print(f"ID решения:             {res.get('decision_id')}")
    print(f"Статус обоснования:     {res.get('new_status', res.get('provenance_status', 'UNKNOWN')).upper()}")
    print(f"Записано в DataHub:     {res.get('written_to_datahub')}")
    if res.get("stale_reason"):
        print(f"Причина устаревания:\n  {res.get('stale_reason')}")
    print("=" * 80)


if __name__ == "__main__":
    main()
