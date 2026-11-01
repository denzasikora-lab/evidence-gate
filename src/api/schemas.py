from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class ValidationResult(BaseModel):
    result: Literal["passed", "failed", "unavailable"]
    reason: str


class ChangeRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "change_id": "cr-net-revenue-001",
                "change_type": "field_rename",
                "source_asset": "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)",
                "old_field": "order_total",
                "new_field": "recognized_revenue",
                "old_type": "decimal",
                "new_type": "decimal",
                "pr_url": "https://github.com/example/repo/pull/42",
                "semantic_mapping": "exact",
            }
        }
    )

    change_id: str
    change_type: Literal["field_rename"] = "field_rename"
    source_asset: str
    old_field: str
    new_field: str
    old_type: str
    new_type: str
    pr_url: str
    semantic_mapping: Optional[Literal["exact", "compatible", "incompatible", "ambiguous"]] = None


class DecisionReceipt(BaseModel):
    decision_id: str
    status: Literal["needs-review", "approved", "blocked"]
    change_url: str
    business_rationale: str
    affected_assets: List[str]
    graph_snapshot_at: str
    risk_score: int = Field(ge=0, le=100)
    evidence_checked: List[str]
    validation: ValidationResult
    required_approvers: List[str]
    unowned_assets_needing_escalation: List[str] = Field(default_factory=list)
    recommended_action: str
    revalidate_after: str
    invalidation_inputs: List[str]
