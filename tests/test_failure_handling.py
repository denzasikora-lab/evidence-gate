import tempfile
from pathlib import Path
import pytest

from src.api.schemas import ChangeRequest
from src.discovery.parser import parse_change_request
from src.evidence.schemas import (
    EvidenceBundle,
    OwnerRef,
    DownstreamConsumer,
)
from src.decision.risk_engine import evaluate_risk
from src.validation.engine import validate_revenue_compatibility
from src.decision.evaluator import build_decision_receipt


# ==============================================================================
# Failure Handling Test 1: MISSING OWNER
# ==============================================================================
def test_failure_handling_missing_owner():
    """
    Case 1: An asset (or its downstream consumers) has no owner assigned in DataHub.
    Asserts that evaluate_risk and build_decision_receipt do not crash or silently produce an
    empty approvers list, but explicitly produce 'UNASSIGNED - <name> has no owner in DataHub, escalate manually'
    entries in required_approvers.
    """
    req = ChangeRequest(
        change_id="cr-test-unowned",
        change_type="field_rename",
        source_asset="urn:li:dataset:(urn:li:dataPlatform:snowflake,orphan_db.public.orphan_table,PROD)",
        old_field="col_a",
        new_field="col_b",
        old_type="int",
        new_type="int",
        pr_url="https://github.com/example/repo/pull/101",
    )

    # Synthetic bundle where source asset has NO owners and one downstream consumer has NO owners
    bundle = EvidenceBundle(
        asset_urn=req.source_asset,
        asset_name="orphan_table",
        field_name=req.old_field,
        asset_owners=[],  # No owner assigned for source asset!
        downstream_consumers=[
            DownstreamConsumer(
                urn="urn:li:dataset:(urn:li:dataPlatform:powerbi,unowned_dashboard,PROD)",
                name="Unowned BI Dashboard",
                platform="powerbi",
                owners=[],  # No owner assigned for downstream consumer!
            )
        ],
        has_bi_consumer=True,
    )

    risk = evaluate_risk(req, bundle)

    assert risk.required_approvers == []
    assert "orphan_table" in risk.unowned_assets_needing_escalation
    assert "Unowned BI Dashboard" in risk.unowned_assets_needing_escalation

    val_report = validate_revenue_compatibility()
    receipt = build_decision_receipt(req, bundle, risk, val_report)
    assert receipt.required_approvers == []
    assert "orphan_table" in receipt.unowned_assets_needing_escalation
    assert "Unowned BI Dashboard" in receipt.unowned_assets_needing_escalation


# ==============================================================================
# Failure Handling Test 2: MISSING/BROKEN LINEAGE
# ==============================================================================
def test_failure_handling_genuinely_empty_lineage():
    """
    Case 2a: Genuinely empty downstream lineage triggers the 'no downstream consumers'
    risk-reducing rule (-20 risk score).
    """
    req = ChangeRequest(
        change_id="cr-test-empty-lineage",
        change_type="field_rename",
        source_asset="urn:li:dataset:(urn:li:dataPlatform:snowflake,db.schema.isolated_table,PROD)",
        old_field="col_x",
        new_field="col_y",
        old_type="int",
        new_type="int",
        pr_url="https://github.com/example/repo/pull/102",
    )

    bundle = EvidenceBundle(
        asset_urn=req.source_asset,
        field_name=req.old_field,
        asset_owners=[OwnerRef(urn="urn:li:corpuser:alice", name="Alice Smith")],
        downstream_consumers=[],  # Genuinely empty
        unresolvable_lineage_urns=[],  # No broken lineage
    )

    risk = evaluate_risk(req, bundle)
    assert "no_downstream_consumers" in risk.signals_triggered
    assert risk.risk_score == 0
    assert risk.leaning == "approved"


def test_failure_handling_broken_lineage_edge():
    """
    Case 2b: A lineage edge exists but points to an unresolvable URN (deleted/renamed asset).
    Asserts that the pipeline does NOT treat this as 'no downstream consumers' (-20 risk score),
    logs/flags 'unresolvable_lineage_edge' distinctly, and does not crash.
    """
    req = ChangeRequest(
        change_id="cr-test-broken-lineage",
        change_type="field_rename",
        source_asset="urn:li:dataset:(urn:li:dataPlatform:snowflake,db.schema.source_table,PROD)",
        old_field="col_x",
        new_field="col_y",
        old_type="int",
        new_type="int",
        pr_url="https://github.com/example/repo/pull/103",
    )

    bundle = EvidenceBundle(
        asset_urn=req.source_asset,
        field_name=req.old_field,
        asset_owners=[OwnerRef(urn="urn:li:corpuser:alice", name="Alice Smith")],
        downstream_consumers=[],  # 0 resolved consumers
        unresolvable_lineage_urns=[
            "urn:li:dataset:(urn:li:dataPlatform:snowflake,db.schema.deleted_consumer,PROD)"
        ],  # But 1 unresolvable lineage edge!
    )

    risk = evaluate_risk(req, bundle)
    # Must NOT trigger risk-reducing 'no_downstream_consumers' rule!
    assert "no_downstream_consumers" not in risk.signals_triggered
    # Must flag 'unresolvable_lineage_edge' distinctly
    assert "unresolvable_lineage_edge" in risk.signals_triggered
    assert risk.risk_score == 25


# ==============================================================================
# Failure Handling Test 3: UNAVAILABLE VALIDATION SOURCE
# ==============================================================================
def test_failure_handling_missing_validation_source():
    """
    Case 3a: Fixture CSV file is missing.
    Asserts validate_revenue_compatibility does not crash the pipeline, but returns
    validation.result = 'unavailable', and build_decision_receipt defaults to 'needs-review'.
    """
    val_report = validate_revenue_compatibility(csv_path="fixtures/nonexistent_file_path_123.csv")
    assert val_report.result == "unavailable"
    assert "CSV-фикстура не найдена" in val_report.reason

    req = ChangeRequest(
        change_id="cr-test-missing-val",
        change_type="field_rename",
        source_asset="urn:li:dataset:(urn:li:dataPlatform:snowflake,db.schema.table,PROD)",
        old_field="amount",
        new_field="new_amount",
        old_type="decimal",
        new_type="decimal",
        pr_url="https://github.com/example/repo/pull/104",
    )
    bundle = EvidenceBundle(
        asset_urn=req.source_asset,
        field_name=req.old_field,
        asset_owners=[OwnerRef(urn="urn:li:corpuser:alice", name="Alice Smith")],
        downstream_consumers=[],
    )
    risk = evaluate_risk(req, bundle)

    receipt = build_decision_receipt(req, bundle, risk, val_report)
    assert receipt.validation.result == "unavailable"
    assert receipt.status == "needs-review"
    assert receipt.risk_score >= 50
    assert "Источник проверки недоступен" in receipt.recommended_action


def test_failure_handling_corrupted_validation_source():
    """
    Case 3b: Fixture CSV file is corrupted or DuckDB query throws.
    Asserts validate_revenue_compatibility catches exception, returns result='unavailable',
    and decision receipt defaults to 'needs-review'.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as tmp:
        tmp.write("invalid,header,row\nfoo,bar,baz\n")
        tmp_path = tmp.name

    try:
        val_report = validate_revenue_compatibility(csv_path=tmp_path)
        assert val_report.result == "unavailable"
        assert "Источник проверки недоступен" in val_report.reason
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ==============================================================================
# Failure Handling Test 4: AMBIGUOUS SEMANTIC MAPPING
# ==============================================================================
def test_failure_handling_ambiguous_semantic_mapping():
    """
    Case 4: Schema-diff parser encounters a change where old_type and new_type are genuinely incompatible
    in a way that cannot be determined from available metadata (e.g. 'variant' -> 'geometry').
    Asserts parser flags this explicitly ('semantic_mapping': 'ambiguous') and risk engine
    flags 'ambiguous_semantic_mapping' rather than guessing pass or fail.
    """
    payload = {
        "change_id": "cr-test-ambiguous-type",
        "change_type": "field_rename",
        "source_asset": "urn:li:dataset:(urn:li:dataPlatform:snowflake,db.schema.complex_table,PROD)",
        "old_field": "raw_payload",
        "new_field": "spatial_data",
        "old_type": "variant",
        "new_type": "geometry",
        "pr_url": "https://github.com/example/repo/pull/105",
    }

    req = parse_change_request(payload)
    assert req.semantic_mapping == "ambiguous"

    bundle = EvidenceBundle(
        asset_urn=req.source_asset,
        field_name=req.old_field,
        asset_owners=[OwnerRef(urn="urn:li:corpuser:alice", name="Alice Smith")],
        downstream_consumers=[],
    )

    risk = evaluate_risk(req, bundle)
    assert "ambiguous_semantic_mapping" in risk.signals_triggered
    assert risk.leaning == "needs-review"
    assert risk.risk_score >= 50

    from src.validation.schemas import RevenueValidationReport
    val_report = RevenueValidationReport(
        result="passed",
        reason="Validation passed: aggregate matches",
        old_aggregate=100.0,
        proposed_aggregate=100.0,
        delta_pct=0.0,
    )
    receipt = build_decision_receipt(req, bundle, risk, val_report)
    assert receipt.status == "needs-review"
    assert "ambiguous" in receipt.business_rationale.lower() or "ambiguous" in risk.signals_triggered
