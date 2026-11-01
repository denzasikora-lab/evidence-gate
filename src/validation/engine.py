from pathlib import Path
from typing import Union
import duckdb
from src.validation.schemas import RevenueValidationReport


# Разрешённый список запросов сравнения согласно ограничению Evidence Gate № 3.
ALLOWLISTED_REVENUE_COMPATIBILITY_QUERY = """
SELECT 
    ROUND(SUM(order_total), 2) AS old_aggregate,
    ROUND(SUM(CASE 
        WHEN order_status NOT IN ('refunded', 'cancelled') 
        THEN (order_total - tax_amount) 
        ELSE 0 
    END), 2) AS proposed_aggregate
FROM orders;
"""


def validate_revenue_compatibility(
    csv_path: Union[str, Path] = "fixtures/order_book_fixture.csv",
    tolerance_pct: float = 1.0,
) -> RevenueValidationReport:
    """
    Выполняет разрешённый запрос совместимости DuckDB для фикстуры книги заказов.
    Вычисляет прежний агрегат SUM(order_total) и предложенный агрегат recognized_revenue,
    затем возвращает RevenueValidationReport с результатом по заданному допуску.
    """
    path = Path(csv_path)
    try:
        if not path.exists():
            return RevenueValidationReport(
                result="unavailable",
                reason=f"Источник проверки недоступен: CSV-фикстура не найдена по пути {path}",
                old_aggregate=0.0,
                proposed_aggregate=0.0,
                delta_pct=0.0,
                tolerance_pct=tolerance_pct,
            )

        conn = duckdb.connect(database=":memory:")
        # Загружаем CSV синтетической книги заказов в таблицу DuckDB в памяти.
        conn.execute(f"CREATE TABLE orders AS SELECT * FROM read_csv_auto('{path}')")

        row = conn.execute(ALLOWLISTED_REVENUE_COMPATIBILITY_QUERY).fetchone()
        if not row or row[0] is None:
            return RevenueValidationReport(
                result="unavailable",
                reason="Источник проверки недоступен: не удалось вычислить агрегаты дохода запросом DuckDB",
                old_aggregate=0.0,
                proposed_aggregate=0.0,
                delta_pct=0.0,
                tolerance_pct=tolerance_pct,
            )
    except Exception as e:
        return RevenueValidationReport(
            result="unavailable",
            reason=f"Источник проверки недоступен: {e}",
            old_aggregate=0.0,
            proposed_aggregate=0.0,
            delta_pct=0.0,
            tolerance_pct=tolerance_pct,
        )

    old_aggregate = float(row[0])
    proposed_aggregate = float(row[1])

    if old_aggregate == 0.0:
        delta_pct = 0.0
    else:
        delta_pct = (abs(old_aggregate - proposed_aggregate) / old_aggregate) * 100.0

    delta_pct = round(delta_pct, 4)
    passed = delta_pct <= tolerance_pct

    if passed:
        result = "passed"
        reason = (
            f"Проверка пройдена: агрегат дохода изменился на {delta_pct:.2f}% "
            f"(в пределах допустимого отклонения {tolerance_pct:.2f}%)."
        )
    else:
        result = "failed"
        reason = (
            f"Проверка не пройдена: агрегат дохода изменился на {delta_pct:.2f}% "
            f"(превышает допустимое отклонение {tolerance_pct:.2f}%). "
            f"Прежний SUM(order_total) = ${old_aggregate:,.2f}, предложенный признанный доход = ${proposed_aggregate:,.2f}."
        )

    return RevenueValidationReport(
        result=result,
        reason=reason,
        old_aggregate=old_aggregate,
        proposed_aggregate=proposed_aggregate,
        delta_pct=delta_pct,
        tolerance_pct=tolerance_pct,
    )
