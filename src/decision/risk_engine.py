from typing import List, Set
from src.api.schemas import ChangeRequest
from src.evidence.schemas import EvidenceBundle
from src.decision.schemas import RiskAssessment


REVENUE_TERMS = {"revenue", "order total"}
REVENUE_TERM_URNS = {
    "urn:li:glossaryTerm:b2fd91.26e268c3-3688-4281-949e-8c1aa2600c02",  # Доход по классу клиента
    "urn:li:glossaryTerm:b2fd91.42266719-3cab-42b8-a8d2-49d782876dbc",  # Сумма заказа
}


def is_revenue_glossary_term(term_urn: str, term_name: str) -> bool:
    """Проверяет, соответствует ли термин глоссария семантике дохода (по URN или имени)."""
    if term_urn in REVENUE_TERM_URNS:
        return True
    name_lower = term_name.lower()
    return any(rt in name_lower for rt in REVENUE_TERMS)


def evaluate_risk(change_request: ChangeRequest, evidence: EvidenceBundle) -> RiskAssessment:
    """
    Оценивает детерминированные правила риска из таблицы SKILL.md для ChangeRequest
    и его EvidenceBundle. Возвращает числовой балл риска (0–100) и предварительный статус
    ('needs-review', 'approved', 'blocked').
    """
    signals: List[str] = []
    blocking_reasons: List[str] = []
    score = 0

    # Правило 3: у нового поля несовместимый тип или семантическое определение.
    if change_request.semantic_mapping == "ambiguous":
        signals.append("ambiguous_semantic_mapping")
        score += 50
    elif change_request.old_type.lower() != change_request.new_type.lower() or change_request.semantic_mapping == "incompatible":
        signals.append("incompatible_field_type")
        blocking_reasons.append(
            f"Тип поля изменён с '{change_request.old_type}' на '{change_request.new_type}'"
        )

    # Правило 6: существующая проверка качества завершается неуспешно.
    if evidence.failing_assertions:
        signals.append("failing_quality_assertion")
        blocking_reasons.append(
            f"Количество неуспешных проверок качества: {len(evidence.failing_assertions)}"
        )

    # Правило 1: путь происхождения к руководящему дашборду (упрощение: любой зависимый BI-дашборд).
    if evidence.has_bi_consumer or any(c.platform in {"powerbi", "tableau", "looker"} for c in evidence.downstream_consumers):
        signals.append("downstream_bi_consumer_present")
        score += 35

    # Правило 2: поле связано с термином глоссария, например «Доход».
    revenue_terms_found = [
        t for t in evidence.all_glossary_terms
        if is_revenue_glossary_term(t.urn, t.name)
    ]
    if revenue_terms_found:
        signals.append("revenue_glossary_term_linked")
        score += 40

    # Правило 5: нет зависимых потребителей (снижение риска) — только если нет и разрывов происхождения.
    if evidence.unresolvable_lineage_urns:
        signals.append("unresolvable_lineage_edge")
        score += 25
    elif len(evidence.downstream_consumers) == 0:
        signals.append("no_downstream_consumers")
        score -= 20

    # Собираем обязательных согласующих (только реальных именованных людей) и активы без владельцев.
    approver_names: Set[str] = set()
    unowned_assets: Set[str] = set()

    # Владельцы актива
    asset_human_owners = set()
    for o in evidence.asset_owners:
        if o.name and not o.name.startswith("b2fd91.") and not o.name.startswith("urn:li:"):
            asset_human_owners.add(o.name)
    if asset_human_owners:
        approver_names.update(asset_human_owners)
    else:
        asset_label = getattr(evidence, "asset_name", None) or change_request.source_asset
        unowned_assets.add(asset_label)

    # Владельцы зависимых потребителей
    for c in evidence.downstream_consumers:
        consumer_human_owners = set()
        for o in c.owners:
            if o.name and not o.name.startswith("b2fd91.") and not o.name.startswith("urn:li:"):
                consumer_human_owners.add(o.name)
        if consumer_human_owners:
            approver_names.update(consumer_human_owners)
        else:
            consumer_label = c.name or c.urn
            unowned_assets.add(consumer_label)

    required_approvers = sorted(list(approver_names))
    unowned_assets_needing_escalation = sorted(list(unowned_assets))

    # Определяем предварительный статус.
    if blocking_reasons:
        final_score = 100
        leaning = "blocked"
        rationale = f"Изменение заблокировано из-за нарушений детерминированных правил: {'; '.join(blocking_reasons)}."
    else:
        final_score = max(0, min(100, score))
        if "ambiguous_semantic_mapping" in signals:
            final_score = max(50, final_score)

        if final_score >= 50:
            leaning = "needs-review"
            rationale = (
                f"Предварительный статус: needs-review (балл риска {final_score}/100) из-за "
                f"сигналов: {', '.join(signals)}."
            )
        else:
            leaning = "approved"
            rationale = (
                f"Предварительный статус: approved (балл риска {final_score}/100); сигналы: {', '.join(signals)}."
            )

    return RiskAssessment(
        risk_score=final_score,
        leaning=leaning,
        signals_triggered=signals,
        required_approvers=required_approvers,
        unowned_assets_needing_escalation=unowned_assets_needing_escalation,
        rationale=rationale,
    )
