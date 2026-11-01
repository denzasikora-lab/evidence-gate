import os
import sys
from typing import List
from dotenv import load_dotenv
from google import genai

from src.api.schemas import ChangeRequest
from src.decision.schemas import RiskAssessment
from src.validation.schemas import RevenueValidationReport

# Автоматически загружаем переменные окружения из .env, если файл существует.
load_dotenv()

# Единая конфигурация модели для всего кода.
MODEL_NAME = "gemini-3.5-flash"

SIGNAL_HUMAN_NAMES = {
    "downstream_bi_consumer_present": "У поля есть реальные зависимые потребители BI/дашборды",
    "revenue_glossary_term_linked": "Поле связано с критически важными терминами глоссария дохода",
    "incompatible_field_type": "Тип поля изменился между источником и назначением",
    "failing_quality_assertion": "Существующие проверки качества данных сейчас не проходят",
    "no_downstream_consumers": "Нет затронутых зависимых потребителей",
    "unresolvable_lineage_edge": "В DataHub обнаружена неразрешимая связь происхождения",
    "ambiguous_semantic_mapping": "Переход типа поля имеет неоднозначную семантическую совместимость",
}

GLOBAL_FORBIDDEN_PHRASES = [
    "executive",
    "exec dashboard",
    "руководящий",
    "исполнительный дашборд",
]

FORBIDDEN_PHRASES_BY_SIGNAL = {
    "incompatible_field_type": [
        "incompatible type",
        "incompatible field",
        "type mismatch",
        "type incompatibility",
        "type change",
        "type conversion",
        "differing type",
        "different type",
        "несовместимый тип",
        "несовместимый тип поля",
        "несовместимость типов",
        "изменение типа",
    ],
    "failing_quality_assertion": [
        "failing quality assertion",
        "assertion failure",
        "failing assertion",
        "quality assertion failure",
        "quality assertion failing",
        "quality assertion",
        "data quality check",
        "assertion check",
        "неуспешная проверка качества",
        "проверка качества не пройдена",
        "сбой проверки качества",
    ],
}


NO_DOWNSTREAM_HALLUCINATION_PHRASES = [
    "no downstream consumer",
    "no downstream consumers",
    "despite having no downstream",
    "having no downstream",
    "with no downstream",
    "without downstream",
    "no bi consumer",
    "no bi consumers",
    "no downstream dashboard",
    "no downstream dashboards",
    "нет зависимых потребителей",
    "нет зависимых активов",
    "без зависимых потребителей",
    "нет зависимых дашбордов",
]


def _build_fallback_rationale(
    change_request: ChangeRequest,
    risk_assessment: RiskAssessment,
    validation_report: RevenueValidationReport,
    final_status: str,
) -> str:
    """Формирует статическое шаблонное обоснование как резервный вариант."""
    if validation_report.result == "failed":
        return (
            f"Изменение ЗАБЛОКИРОВАНО: переименование поля '{change_request.old_field}' -> '{change_request.new_field}' "
            f"вызывает расхождение метрики. {validation_report.reason}"
        )
    elif validation_report.result == "unavailable":
        return (
            f"Изменение ТРЕБУЕТ ПРОВЕРКИ: переименование поля '{change_request.old_field}' -> '{change_request.new_field}' "
            f"требует ручной проверки, потому что источник проверки недоступен: {validation_report.reason}"
        )
    elif risk_assessment.leaning == "blocked":
        return f"Изменение ЗАБЛОКИРОВАНО: {risk_assessment.rationale}"
    elif final_status == "needs-review":
        return f"Изменение ТРЕБУЕТ ПРОВЕРКИ: {risk_assessment.rationale}"
    else:
        return f"Изменение УТВЕРЖДЕНО: {risk_assessment.rationale}"


def _detect_hallucinated_signals(text: str, triggered_signals: List[str]) -> bool:
    """
    Возвращает True, если сгенерированный текст ссылается на категории сигналов,
    которые не сработали, содержит запрещённые фразы или противоречит фактам о зависимых потребителях.
    """
    text_lower = text.lower()
    for phrase in GLOBAL_FORBIDDEN_PHRASES:
        if phrase in text_lower:
            return True

    for signal_key, forbidden_phrases in FORBIDDEN_PHRASES_BY_SIGNAL.items():
        if signal_key not in triggered_signals:
            for phrase in forbidden_phrases:
                if phrase in text_lower:
                    return True

    if "downstream_bi_consumer_present" in triggered_signals:
        for phrase in NO_DOWNSTREAM_HALLUCINATION_PHRASES:
            if phrase in text_lower:
                return True

    return False


def generate_business_rationale(
    change_request: ChangeRequest,
    risk_assessment: RiskAssessment,
    validation_report: RevenueValidationReport,
    final_status: str,
    final_risk_score: int,
) -> str:
    """
    Генерирует естественно-языковое обоснование с помощью Gemini LLM.
    Статус и балл риска передаются как ФИКСИРОВАННЫЕ, детерминированные входные данные.
    В подсказку попадают только сработавшие сигналы, а результат проверяется на галлюцинации.
    """
    fallback_rationale = _build_fallback_rationale(
        change_request, risk_assessment, validation_report, final_status
    )

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        warning_msg = (
            "[LLM_UNAVAILABLE] Используется шаблонное обоснование — "
            "вызов Gemini не выполнен: переменная окружения GEMINI_API_KEY не задана."
        )
        print(warning_msg, file=sys.stderr)
        return fallback_rationale

    # Construct list containing ONLY risk signals that actually triggered
    triggered_bullets = [
        f"  - {SIGNAL_HUMAN_NAMES.get(sig, sig)}"
        for sig in risk_assessment.signals_triggered
    ]
    signals_fact_text = (
        "\n".join(triggered_bullets)
        if triggered_bullets
        else "  - Нет (сигналы риска не сработали)"
    )

    try:
        client = genai.Client(api_key=api_key)
        prompt = f"""
Вы — Evidence Gate, автоматизированный механизм управления данными и фиксации обоснований решений.
Сформулируйте краткое профессиональное обоснование автоматической оценки запроса на изменение (2–3 предложения).

ФАКТЫ ДЕТЕРМИНИРОВАННОЙ ОЦЕНКИ (ФИКСИРОВАНЫ — НЕ ИЗМЕНЯЙТЕ):
- Итоговый статус решения: {final_status.upper()}
- Числовой балл риска: {final_risk_score}/100
- Переход поля: '{change_request.old_field}' ({change_request.old_type}) -> '{change_request.new_field}' ({change_request.new_type})
- URN исходного актива: {change_request.source_asset}
- Сработавшие сигналы риска (СРАБОТАЛИ ТОЛЬКО ОНИ):
{signals_fact_text}
- Результат проверки метрики дохода: {validation_report.result.upper()}
- Изменение агрегата метрики (дельта): {validation_report.delta_pct:.2f}% (допустимое отклонение: {validation_report.tolerance_pct:.2f}%)
- Детали проверки: {validation_report.reason}

ИНСТРУКЦИИ:
1. Объясните обоснование решения в 2–3 ясных профессиональных предложениях, СТРОГО опираясь на детерминированные факты выше.
2. Укажите точный статус решения ({final_status.upper()}), балл риска ({final_risk_score}/100) и процент дельты метрики ({validation_report.delta_pct:.2f}%).
3. Упоминайте только сигналы из раздела «Сработавшие сигналы риска». Не выводите, не предполагаете и не упоминайте фактор риска, сигнал или причину, которых нет в фактах (например, несовместимость типов или неуспешные проверки качества), даже если это кажется правдоподобным для заблокированного изменения. Типы полей совпадают ('{change_request.old_type}' и '{change_request.new_type}'), а проверки качества не завершались ошибкой. Если в сработавших сигналах указано «У поля есть реальные зависимые потребители BI/дашборды», не заявляйте и не подразумевайте отсутствие затронутых зависимых потребителей. Не используйте слова «руководящий» или «исполнительный дашборд».
4. Ответьте ТОЛЬКО текстом обоснования на русском языке.
"""
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )
        text = response.text.strip() if response and response.text else ""
        if not text:
            raise ValueError("Gemini returned empty response text.")

        # Проверка безопасности после генерации: ищем галлюцинации о несработавших сигналах.
        if _detect_hallucinated_signals(text, risk_assessment.signals_triggered):
            warning_msg = (
                "[LLM_HALLUCINATION_DETECTED] В ответе Gemini упомянуты сигналы, которых нет "
                "во входных фактах — используется шаблон."
            )
            print(warning_msg, file=sys.stderr)
            return fallback_rationale

        return text
    except Exception as e:
        warning_msg = (
            f"[LLM_UNAVAILABLE] Используется шаблонное обоснование — вызов Gemini не выполнен: {e}"
        )
        print(warning_msg, file=sys.stderr)
        return fallback_rationale
