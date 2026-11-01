import os
import sys
import pytest
from unittest.mock import patch, MagicMock

from src.api.schemas import ChangeRequest
from src.decision.schemas import RiskAssessment
from src.validation.schemas import RevenueValidationReport
from src.decision.narrator import generate_business_rationale, _detect_hallucinated_signals
from src.decision.evaluator import build_decision_receipt
from src.evidence.schemas import EvidenceBundle
from src.precedent.retriever import narrate_precedent_comparison


@pytest.fixture
def sample_inputs():
    req = ChangeRequest(
        change_id="cr-test-001",
        change_type="field_rename",
        source_asset="urn:li:dataset:(urn:li:dataPlatform:snowflake,db.schema.table,PROD)",
        old_field="order_total",
        new_field="recognized_revenue",
        old_type="decimal",
        new_type="decimal",
        pr_url="https://github.com/example/repo/pull/1",
    )
    evidence = EvidenceBundle(asset_urn=req.source_asset, field_name=req.old_field)
    risk = RiskAssessment(
        risk_score=75,
        leaning="needs-review",
        signals_triggered=["downstream_bi_consumer_present", "revenue_glossary_term_linked"],
        required_approvers=["David Kim"],
        rationale="Preliminary leaning is needs-review",
    )
    val = RevenueValidationReport(
        result="failed",
        reason="Validation failed: Revenue aggregate shifted by 13.16% (exceeds allowed tolerance of 1.00%). Old SUM(order_total) = $18,789.67, Proposed Recognized Revenue = $16,317.15.",
        old_aggregate=18789.67,
        proposed_aggregate=16317.15,
        delta_pct=13.1589,
        tolerance_pct=1.0,
    )
    return req, evidence, risk, val


def test_determinism_status_and_risk_score_unaffected_by_llm(sample_inputs):
    """
    Requirement 5: Confirm that structural decision outcomes (status, risk_score) remain
    100% deterministic and unaffected by LLM output.
    """
    req, evidence, risk, val = sample_inputs
    receipt1 = build_decision_receipt(req, evidence, risk, val)
    receipt2 = build_decision_receipt(req, evidence, risk, val)

    assert receipt1.status == receipt2.status == "blocked"
    assert receipt1.risk_score == receipt2.risk_score == 100


def test_fallback_when_gemini_api_key_missing(sample_inputs, capsys):
    """
    Requirement 4 & 5: When GEMINI_API_KEY is missing, system logs a clear warning
    and falls back to the static template rationale containing all key facts.
    """
    req, evidence, risk, val = sample_inputs

    with patch.dict(os.environ, {}, clear=True):

        rationale = generate_business_rationale(
            change_request=req,
            risk_assessment=risk,
            validation_report=val,
            final_status="blocked",
            final_risk_score=100,
        )

        captured = capsys.readouterr()
        assert "[LLM_UNAVAILABLE]" in captured.err or "[LLM_UNAVAILABLE]" in captured.out
        assert "Используется шаблонное обоснование" in captured.err or captured.out
        assert "order_total" in rationale
        assert "recognized_revenue" in rationale
        assert "Изменение ЗАБЛОКИРОВАНО" in rationale


def test_fallback_when_gemini_api_call_raises_exception(sample_inputs, capsys):
    """
    Requirement 4 & 5: When Gemini API raises an exception, system catches it,
    prints the visible warning, and falls back gracefully.
    """
    req, evidence, risk, val = sample_inputs

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key-for-test"}):
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.models.generate_content.side_effect = RuntimeError("API quota exceeded or network error")
            mock_client_cls.return_value = mock_client

            rationale = generate_business_rationale(
                change_request=req,
                risk_assessment=risk,
                validation_report=val,
                final_status="blocked",
                final_risk_score=100,
            )

            captured = capsys.readouterr()
            assert "[LLM_UNAVAILABLE]" in captured.err or "[LLM_UNAVAILABLE]" in captured.out
            assert "API quota exceeded or network error" in captured.err or captured.out
            assert "Изменение ЗАБЛОКИРОВАНО" in rationale
            assert "order_total" in rationale


def test_hallucination_detection_triggers_fallback(sample_inputs, capsys):
    """
    Requirement 3: Verifies that post-generation validation catches hallucinated
    non-triggered risk signals (e.g. incompatible field type or failing quality assertions)
    and falls back to template with [LLM_HALLUCINATION_DETECTED] warning.
    """
    req, evidence, risk, val = sample_inputs

    hallucinated_text = (
        "The change is BLOCKED (100/100) due to incompatible field types and failing quality assertions. "
        "Validation failed with a 13.16% shift."
    )

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-valid-key"}):
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = hallucinated_text
            mock_client.models.generate_content.return_value = mock_response
            mock_client_cls.return_value = mock_client

            rationale = generate_business_rationale(
                change_request=req,
                risk_assessment=risk,
                validation_report=val,
                final_status="blocked",
                final_risk_score=100,
            )

            captured = capsys.readouterr()
            assert "[LLM_HALLUCINATION_DETECTED]" in captured.err or "[LLM_HALLUCINATION_DETECTED]" in captured.out
            assert rationale != hallucinated_text
            assert "Изменение ЗАБЛОКИРОВАНО" in rationale


def test_live_gemini_api_no_hallucinated_signals(sample_inputs):
    """
    Requirement 4: Executes a real API call against Gemini (live API, unmocked) using
    net_revenue_rename.json deterministic facts (matching decimal types, 0 failing assertions).
    Asserts that returned text does NOT contain fabricated-signal language.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not present in environment - skipping live API test")

    req, evidence, risk, val = sample_inputs

    # Ensure inputs match net_revenue_rename case: matching types, no failing assertions
    assert req.old_type == req.new_type == "decimal"
    assert "incompatible_field_type" not in risk.signals_triggered
    assert "failing_quality_assertion" not in risk.signals_triggered

    rationale = generate_business_rationale(
        change_request=req,
        risk_assessment=risk,
        validation_report=val,
        final_status="blocked",
        final_risk_score=100,
    )

    rationale_lower = rationale.lower()

    # Assert live Gemini output does NOT hallucinate type incompatibility or quality assertion failures, nor forbidden executive phrasing or contradicting downstream consumer claims
    assert "incompatible type" not in rationale_lower
    assert "type mismatch" not in rationale_lower
    assert "incompatible field" not in rationale_lower
    assert "failing quality assertion" not in rationale_lower
    assert "assertion failure" not in rationale_lower
    assert "executive" not in rationale_lower
    assert "exec dashboard" not in rationale_lower
    assert "no downstream" not in rationale_lower
    assert "despite having no" not in rationale_lower


def test_live_gemini_api_downstream_consumer_no_hallucination_regression(sample_inputs):
    """
    Regression test: Passes facts where downstream_bi_consumer_present=True,
    calls real Gemini API (unmocked), and asserts output does NOT contain
    'no downstream' or 'despite having no' phrasing.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not present in environment - skipping live API test")

    req, evidence, risk, val = sample_inputs

    assert "downstream_bi_consumer_present" in risk.signals_triggered

    rationale = generate_business_rationale(
        change_request=req,
        risk_assessment=risk,
        validation_report=val,
        final_status="blocked",
        final_risk_score=100,
    )

    rationale_lower = rationale.lower()

    assert "no downstream" not in rationale_lower
    assert "despite having no" not in rationale_lower


def test_downstream_consumer_hallucination_triggers_fallback(sample_inputs, capsys):
    """
    Verifies that when downstream_bi_consumer_present is in signals_triggered,
    hallucinated text claiming 'no downstream consumers' is caught and triggers fallback.
    """
    req, evidence, risk, val = sample_inputs
    assert "downstream_bi_consumer_present" in risk.signals_triggered

    hallucinated_text = (
        "The change is BLOCKED (100/100) despite having no downstream consumers affected. "
        "Validation failed with a 13.16% shift."
    )

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-valid-key"}):
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = hallucinated_text
            mock_client.models.generate_content.return_value = mock_response
            mock_client_cls.return_value = mock_client

            rationale = generate_business_rationale(
                change_request=req,
                risk_assessment=risk,
                validation_report=val,
                final_status="blocked",
                final_risk_score=100,
            )

            captured = capsys.readouterr()
            assert "[LLM_HALLUCINATION_DETECTED]" in captured.err or "[LLM_HALLUCINATION_DETECTED]" in captured.out
            assert rationale != hallucinated_text
            assert "despite having no downstream" not in rationale.lower()
            assert "Изменение ЗАБЛОКИРОВАНО" in rationale


def test_forbidden_phrase_executive_triggers_fallback(sample_inputs, capsys):
    """
    Verifies that post-generation validation catches forbidden 'executive' phrasing
    and falls back to template with [LLM_HALLUCINATION_DETECTED] warning.
    """
    req, evidence, risk, val = sample_inputs

    executive_text = (
        "The change is BLOCKED (100/100) due to downstream executive dashboard consumers. "
        "Validation failed with a 13.16% shift."
    )

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-valid-key"}):
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = executive_text
            mock_client.models.generate_content.return_value = mock_response
            mock_client_cls.return_value = mock_client

            rationale = generate_business_rationale(
                change_request=req,
                risk_assessment=risk,
                validation_report=val,
                final_status="blocked",
                final_risk_score=100,
            )

            captured = capsys.readouterr()
            assert "[LLM_HALLUCINATION_DETECTED]" in captured.err or "[LLM_HALLUCINATION_DETECTED]" in captured.out
            assert rationale != executive_text
            assert "executive" not in rationale.lower()
            assert "Изменение ЗАБЛОКИРОВАНО" in rationale

