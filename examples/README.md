# Указатель каталога примеров

Этот каталог содержит реальные артефакты выполнения Evidence Gate, полученные при работе с GMS DataHub и данными проверки метрик:

- **`change_request.json`** — входная полезная нагрузка диффа схемы `ChangeRequest`, предлагающая заменить `order_total` на `recognized_revenue` в Snowflake `order_details`.
- **`evidence_bundle.json`** — заполненный `EvidenceBundle` с реальными владельцами (`David Kim`, `Julia Novak`), терминами глоссария, 13 зависимыми потребителями происхождения и метаданными проверок качества из DataHub.
- **`blocked_decision_receipt.json`** — итоговая детерминированная полезная нагрузка `DecisionReceipt`, объединяющая правила риска этапа 2 (75) и проверку метрики DuckDB этапа 3 (сдвиг 13,16% → `BLOCKED`).
- **`recognized_revenue_patch.sql`** — созданный патч модели совместимости dbt/SQL для `recognized_revenue`.
- **`test_recognized_revenue_migration.py`** — созданный тест миграции pytest, проверяющий границы и нулевое расхождение.
- **`written_back_provenance.json`** — реальные метаданные, считанные из GMS DataHub после записи: 13 пользовательских свойств набора данных, ссылка на документацию PR и статус операционного инцидента.
