import os
from typing import Dict, Any, Optional
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig


def retrieve_decision_provenance(
    asset_urn: str, gms_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Независимо запрашивает живой граф метаданных DataHub для заданного URN актива,
    читает сохранённые пользовательские свойства Decision Provenance и возвращает структурированный отчёт.
    Не использует состояние приложения в памяти.
    """
    target_gms_url = gms_url or os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
    graph = DataHubGraph(
        DataHubGraphConfig(
            server=target_gms_url,
            token=os.getenv("DATAHUB_GMS_TOKEN") or None,
        )
    )

    query = """
    query getDatasetProvenance($urn: String!) {
      dataset(urn: $urn) {
        urn
        properties {
          name
          customProperties {
            key
            value
          }
        }
        institutionalMemory {
          elements {
            url
            description
          }
        }
      }
    }
    """

    res = graph.execute_graphql(query, variables={"urn": asset_urn})
    dataset_data = res.get("dataset") if res else None
    if not dataset_data or not dataset_data.get("properties"):
        return {"error": f"В DataHub не найден актив с URN: {asset_urn}"}

    custom_props_list = dataset_data["properties"].get("customProperties") or []
    props_map = {item["key"]: item["value"] for item in custom_props_list}

    if "eg_decision_id" not in props_map:
        return {
            "asset_urn": asset_urn,
            "has_provenance": False,
            "message": "Для этого актива не найдено обоснование решения Evidence Gate.",
        }

    links = dataset_data.get("institutionalMemory", {}).get("elements", [])

    return {
        "asset_urn": asset_urn,
        "asset_name": dataset_data["properties"].get("name"),
        "has_provenance": True,
        "decision_id": props_map.get("eg_decision_id"),
        "status": props_map.get("eg_status"),
        "provenance_status": props_map.get("eg_provenance_status", "active"),
        "stale_reason": props_map.get("eg_stale_reason"),
        "risk_score": int(props_map.get("eg_risk_score", 0)),
        "business_rationale": props_map.get("eg_business_rationale"),
        "validation_result": props_map.get("eg_validation_result"),
        "validation_reason": props_map.get("eg_validation_reason"),
        "required_approvers": [
            a.strip()
            for a in props_map.get("eg_required_approvers", "").split(",")
            if a.strip()
        ],
        "unowned_assets_needing_escalation": [
            u.strip()
            for u in props_map.get("eg_unowned_assets_needing_escalation", "").split(",")
            if u.strip()
        ],
        "recommended_action": props_map.get("eg_recommended_action"),
        "revalidate_after": props_map.get("eg_revalidate_after"),
        "invalidation_inputs": [
            i.strip()
            for i in props_map.get("eg_invalidation_inputs", "").split(",")
            if i.strip()
        ],
        "change_url": props_map.get("eg_change_url"),
        "links": links,
    }
