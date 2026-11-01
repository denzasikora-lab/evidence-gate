from datetime import datetime, timezone, timedelta
from typing import Optional
from src.api.schemas import ChangeRequest, DecisionReceipt, ValidationResult
from src.evidence.schemas import EvidenceBundle
from src.decision.schemas import RiskAssessment
from src.validation.schemas import RevenueValidationReport
from src.decision.narrator import generate_business_rationale


def build_decision_receipt(
    change_request: ChangeRequest,
    evidence: EvidenceBundle,
    risk_assessment: RiskAssessment,
    validation_report: RevenueValidationReport,
    decision_id: str = "eg-2026-001",
) -> DecisionReceipt:
    """
    Объединяет оценку риска этапа 2 и отчёт проверки метрики этапа 3
    в полный детерминированный артефакт DecisionReceipt.
    """
    now = datetime.now(timezone.utc)
    graph_snapshot_at = now.isoformat()
    revalidate_after = (now + timedelta(days=30)).isoformat()

    evidence_checked = [
        "schema_diff",
        "dataset_ownership",
        "glossary_terms",
        "downstream_lineage",
        "quality_assertions",
        "revenue_compatibility_query",
    ]

    invalidation_inputs = [
        f"dataset_schema:{change_request.source_asset}",
        f"glossary_term_link:{change_request.source_asset}",
        f"downstream_lineage:{change_request.source_asset}",
        f"quality_assertion:{change_request.source_asset}",
    ]

    # Правило объединения: сбой проверки метрики безусловно блокирует изменение,
    # переопределяет предварительный балл риска этапа 2 и устанавливает risk_score=100.
    if validation_report.result == "failed":
        final_status = "blocked"
        final_risk_score = 100
        recommended_action = (
            "Примените сгенерированный патч совместимости dbt (examples/recognized_revenue_patch.sql) "
            "и выполните набор миграционных тестов (examples/test_recognized_revenue_migration.py) "
            "перед повторной отправкой на утверждение."
        )
    elif risk_assessment.leaning == "blocked":
        final_status = "blocked"
        final_risk_score = 100
        recommended_action = "Устраните нарушения детерминированных правил риска до проверки."
    elif validation_report.result == "unavailable":
        final_status = "needs-review"
        final_risk_score = max(50, risk_assessment.risk_score)
        recommended_action = (
            f"Источник для проверки недоступен ({validation_report.reason}). "
            f"Перед утверждением требуется ручная проверка."
        )
    elif risk_assessment.risk_score >= 50:
        final_status = "needs-review"
        final_risk_score = risk_assessment.risk_score
        recommended_action = (
            f"Получите утверждение от указанных согласующих: {', '.join(risk_assessment.required_approvers)}"
        )
    else:
        final_status = "approved"
        final_risk_score = risk_assessment.risk_score
        recommended_action = "Выполните миграцию схемы и обновите зависимые модели."

    business_rationale = generate_business_rationale(
        change_request=change_request,
        risk_assessment=risk_assessment,
        validation_report=validation_report,
        final_status=final_status,
        final_risk_score=final_risk_score,
    )

    val_res = ValidationResult(
        result=validation_report.result,
        reason=validation_report.reason,
    )

    return DecisionReceipt(
        decision_id=decision_id,
        status=final_status,
        change_url=change_request.pr_url,
        business_rationale=business_rationale,
        affected_assets=[change_request.source_asset],
        graph_snapshot_at=graph_snapshot_at,
        risk_score=final_risk_score,
        evidence_checked=evidence_checked,
        validation=val_res,
        required_approvers=risk_assessment.required_approvers,
        unowned_assets_needing_escalation=risk_assessment.unowned_assets_needing_escalation,
        recommended_action=recommended_action,
        revalidate_after=revalidate_after,
        invalidation_inputs=invalidation_inputs,
    )
