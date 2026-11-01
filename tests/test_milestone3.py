import os
from pathlib import Path
import pytest
from src.api.schemas import ChangeRequest
from src.discovery.parser import parse_change_request
from src.evidence.collector import build_evidence_bundle
from src.evidence.schemas import EvidenceBundle
from src.decision.schemas import RiskAssessment
from src.decision.risk_engine import evaluate_risk
from src.validation.schemas import RevenueValidationReport
from src.validation.engine import validate_revenue_compatibility
from src.remediation.patch_generator import generate_remediation_artifacts
from src.decision.evaluator import build_decision_receipt


def test_duckdb_validation_query_and_delta():
    """
    Step 2, 3 & DoD item 1: Executes read-only validation query against synthetic fixture
    and asserts real numeric aggregate delta.
    """
    report = validate_revenue_compatibility()

    assert report.result == "failed"
    assert report.old_aggregate == 18789.67
    assert report.proposed_aggregate == 16317.15
    assert report.delta_pct == 13.1589
    assert report.tolerance_pct == 1.0
    assert "изменился на 13.16%" in report.reason
    assert "превышает допустимое отклонение 1.00%" in report.reason


def test_deterministic_validation_runs_twice():
    """
    Step 8 & DoD item 3: Asserts that running the full validation twice produces
    the exact same numeric delta (13.1589%) and the exact same 'blocked' outcome
    with zero variance across separate runs.
    """
    req = parse_change_request("fixtures/net_revenue_rename.json")
    evidence = build_evidence_bundle(req)
    risk = evaluate_risk(req, evidence)

    # Run 1
    val1 = validate_revenue_compatibility()
    receipt1 = build_decision_receipt(req, evidence, risk, val1)

    # Run 2
    val2 = validate_revenue_compatibility()
    receipt2 = build_decision_receipt(req, evidence, risk, val2)

    # Assert exact deterministic equality
    assert val1.delta_pct == val2.delta_pct == 13.1589
    assert val1.result == val2.result == "failed"
    assert receipt1.status == receipt2.status == "blocked"
    assert receipt1.risk_score == receipt2.risk_score == 100
    assert receipt1.validation.reason == receipt2.validation.reason


def test_validation_failure_overrides_low_risk_score():
    """
    Locks the combination rule in place: validation failure sets risk_score to 100
    and status to 'blocked' regardless of a low Milestone 2 preliminary risk score.
    """
    req = parse_change_request("fixtures/net_revenue_rename.json")
    evidence = EvidenceBundle(asset_urn=req.source_asset, field_name=req.old_field)

    # Low Milestone 2 risk score (e.g. 20)
    low_risk = RiskAssessment(
        risk_score=20,
        leaning="approved",
        signals_triggered=["revenue_glossary_term_linked", "no_downstream_consumers"],
        required_approvers=["David Kim"],
        rationale="Preliminary leaning is approved (risk score 20/100).",
    )

    # Failing validation report
    failing_val = RevenueValidationReport(
        result="failed",
        reason="Validation failed: Revenue aggregate shifted by 13.16%",
        old_aggregate=18789.67,
        proposed_aggregate=16317.15,
        delta_pct=13.1589,
        tolerance_pct=1.0,
    )

    receipt = build_decision_receipt(req, evidence, low_risk, failing_val)

    # Assert that validation failure overrides low Milestone 2 risk score (20 -> 100)
    assert receipt.status == "blocked"
    assert receipt.risk_score == 100
    assert "ЗАБЛОКИРОВАНО" in receipt.business_rationale


def test_validation_success_retains_milestone2_risk_score():
    """
    Locks the combination rule in place: validation success retains the Milestone 2
    preliminary risk score and status leaning.
    """
    req = parse_change_request("fixtures/net_revenue_rename.json")
    evidence = EvidenceBundle(asset_urn=req.source_asset, field_name=req.old_field)

    # Milestone 2 risk score 35
    m2_risk = RiskAssessment(
        risk_score=35,
        leaning="approved",
        signals_triggered=["downstream_bi_consumer_present"],
        required_approvers=["David Kim"],
        rationale="Preliminary leaning is approved (risk score 35/100).",
    )

    # Passing validation report
    passing_val = RevenueValidationReport(
        result="passed",
        reason="Validation passed: Metric delta is within allowed tolerance.",
        old_aggregate=10000.0,
        proposed_aggregate=9980.0,
        delta_pct=0.2,
        tolerance_pct=1.0,
    )

    receipt = build_decision_receipt(req, evidence, m2_risk, passing_val)

    # Assert that passing validation retains Milestone 2 risk score (35) and status
    assert receipt.status == "approved"
    assert receipt.risk_score == 35


def test_remediation_artifacts_generation():
    """
    Step 5, 6 & DoD item 2: Asserts that dbt compatibility patch and migration test file
    are generated and saved into examples/.
    """
    req = parse_change_request("fixtures/net_revenue_rename.json")
    val = validate_revenue_compatibility()

    patch_path, test_path = generate_remediation_artifacts(req, val)

    assert patch_path.exists()
    assert test_path.exists()
    assert patch_path.name == "recognized_revenue_patch.sql"
    assert test_path.name == "test_recognized_revenue_migration.py"

    patch_sql = patch_path.read_text(encoding="utf-8")
    assert "recognized_revenue" in patch_sql
    assert "order_total AS order_total" in patch_sql
    assert "CASE" in patch_sql

    test_py = test_path.read_text(encoding="utf-8")
    assert "test_recognized_revenue_calculation" in test_py
    assert "test_recognized_revenue_bounds_and_non_negative" in test_py


def test_generated_migration_test_executes():
    """Проверяет, что сгенерированный миграционный тест действительно запускается через pytest."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "examples/test_recognized_revenue_migration.py"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "2 passed" in result.stdout
