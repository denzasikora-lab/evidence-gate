import pytest
from src.api.schemas import ChangeRequest
from src.discovery.parser import parse_change_request
from src.evidence.collector import build_evidence_bundle
from src.decision.risk_engine import evaluate_risk
from src.validation.engine import validate_revenue_compatibility
from src.decision.evaluator import build_decision_receipt
from src.writeback.writer import write_decision_provenance
from src.writeback.retriever import retrieve_decision_provenance
from src.invalidation.watcher import (
    simulate_graph_change,
    check_and_invalidate_provenance,
    restore_glossary_terms,
)
from src.precedent.retriever import find_precedent_decisions


def test_writeback_decision_provenance_to_datahub():
    """
    Step 1 & DoD item 1: Write Decision Provenance structured properties, documentation links,
    and incident to live DataHub instance.
    """
    req = parse_change_request("fixtures/net_revenue_rename.json")
    evidence = build_evidence_bundle(req)
    risk = evaluate_risk(req, evidence)
    val = validate_revenue_compatibility()
    receipt = build_decision_receipt(req, evidence, risk, val)

    wb_res = write_decision_provenance(receipt)

    assert wb_res["asset_urn"] == req.source_asset
    assert wb_res["decision_id"] == "eg-2026-001"
    assert wb_res["status"] == "blocked"
    assert wb_res["custom_properties_emitted"] >= 10
    assert wb_res["documentation_link"] == req.pr_url
    assert wb_res["incident_urn"] is not None
    assert "urn:li:incident:" in wb_res["incident_urn"]


def test_independent_retrieval_from_datahub():
    """
    Step 3 & DoD item 2: Fresh query to DataHub GMS to retrieve written-back provenance
    without relying on any in-memory state.
    """
    asset_urn = "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)"
    report = retrieve_decision_provenance(asset_urn)

    assert report["has_provenance"] is True
    assert report["decision_id"] == "eg-2026-001"
    assert report["status"] == "blocked"
    assert report["risk_score"] == 100
    assert "Проверка не пройдена: агрегат дохода изменился на 13.16%" in report["validation_reason"]
    assert "David Kim" in report["required_approvers"]


def test_graph_change_watcher_staleness_flip_on_datahub():
    """
    Step 4 & DoD item 3: Simulates real graph change in DataHub and asserts provenance status
    flips to 'stale' as read directly FROM DataHub GMS.
    Restores original glossary terms in finally block for test idempotency.
    """
    asset_urn = "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)"

    try:
        # Simulate real graph change on DataHub (remove glossary term)
        sim_res = simulate_graph_change(asset_urn, action="remove_glossary_term")
        assert sim_res["status"] == "applied_to_datahub"

        # Watcher checks live graph context vs stored snapshot and invalidates
        inv_res = check_and_invalidate_provenance(asset_urn)
        assert inv_res["new_status"] == "stale"
        assert inv_res["written_to_datahub"] is True
        assert "Glossary term 'Revenue by Customer Class'" in inv_res["stale_reason"]

        # Read directly FROM DataHub in a fresh query to confirm staleness
        retrieved_stale = retrieve_decision_provenance(asset_urn)
        assert retrieved_stale["provenance_status"] == "stale"
    finally:
        # Restore original terms so full test suite remains idempotent
        restore_glossary_terms(asset_urn)


def test_precedent_retrieval_and_comparison():
    """
    Step 5 & DoD item 4: Submits second ChangeRequest and retrieves prior decision as precedent
    with explicit 'what still applies / what differs' comparison.
    """
    req2 = ChangeRequest(
        change_id="cr-order-history-002",
        change_type="field_rename",
        source_asset="urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details_replica,PROD)",
        old_field="order_total",
        new_field="recognized_revenue",
        old_type="decimal",
        new_type="decimal",
        pr_url="https://github.com/example/repo/pull/105",
    )

    prec_res = find_precedent_decisions(req2)

    assert prec_res["precedents_found_count"] >= 1
    precedent = prec_res["precedents"][0]
    assert precedent["precedent_decision_id"] == "eg-2026-001"
    assert precedent["prior_status"] == "blocked"

    # Check explicit comparison clauses (key facts present regardless of LLM phrasing)
    applies = precedent["what_still_applies"]
    differs = precedent["what_differs"]
    assert any("order_total" in item or "recognized_revenue" in item or "metric" in item.lower() for item in applies)
    assert any("asset" in item.lower() or "replica" in item.lower() for item in differs)
    assert any("pull/105" in item or "105" in item or "pr" in item.lower() for item in differs)
