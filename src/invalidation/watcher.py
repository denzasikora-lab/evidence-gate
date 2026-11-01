import os
from typing import Dict, Any, Optional
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    GlossaryTermsClass,
    GlossaryTermAssociationClass,
    AuditStampClass,
)


REVENUE_GLOSSARY_URN = "urn:li:glossaryTerm:b2fd91.26e268c3-3688-4281-949e-8c1aa2600c02"
ORDER_TOTAL_GLOSSARY_URN = "urn:li:glossaryTerm:b2fd91.42266719-3cab-42b8-a8d2-49d782876dbc"
PII_GLOSSARY_URN = "urn:li:glossaryTerm:b2fd91.1598cf93-c199-43a1-8833-fce96faa9a1a"
SOC2_GLOSSARY_URN = "urn:li:glossaryTerm:b2fd91.e7106c45-b307-4eb6-9c8c-e7fff15f095a"

ORIGINAL_GLOSSARY_URNS = [
    PII_GLOSSARY_URN,
    SOC2_GLOSSARY_URN,
    ORDER_TOTAL_GLOSSARY_URN,
    REVENUE_GLOSSARY_URN,
]


def restore_glossary_terms(asset_urn: str, gms_url: Optional[str] = None) -> None:
    """Восстанавливает в DataHub исходные термины глоссария набора showcase-ecommerce."""
    target_gms_url = gms_url or os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
    graph = DataHubGraph(
        DataHubGraphConfig(
            server=target_gms_url,
            token=os.getenv("DATAHUB_GMS_TOKEN") or None,
        )
    )

    mcp = MetadataChangeProposalWrapper(
        entityUrn=asset_urn,
        aspect=GlossaryTermsClass(
            terms=[
                GlossaryTermAssociationClass(urn=urn)
                for urn in ORIGINAL_GLOSSARY_URNS
            ],
            auditStamp=AuditStampClass(time=0, actor="urn:li:corpuser:datahub"),
        ),
    )
    graph.emit_mcp(mcp)


def simulate_graph_change(
    asset_urn: str,
    action: str = "remove_glossary_term",
    gms_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Имитирует реальное значимое изменение графа непосредственно в работающем DataHub.
    Действие 'remove_glossary_term' удаляет «Доход по классу клиента» из терминов глоссария актива.
    """
    target_gms_url = gms_url or os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
    graph = DataHubGraph(
        DataHubGraphConfig(
            server=target_gms_url,
            token=os.getenv("DATAHUB_GMS_TOKEN") or None,
        )
    )

    if action == "remove_glossary_term":
        # Получаем текущие термины.
        query = """
        query getTerms($urn: String!) {
          dataset(urn: $urn) {
            glossaryTerms {
              terms {
                term {
                  urn
                }
              }
            }
          }
        }
        """
        res = graph.execute_graphql(query, variables={"urn": asset_urn})
        current_terms = (
            res.get("dataset", {}).get("glossaryTerms", {}).get("terms", [])
        )

        # Исключаем URN термина глоссария дохода.
        remaining_urns = [
            t["term"]["urn"]
            for t in current_terms
            if t.get("term", {}).get("urn") != REVENUE_GLOSSARY_URN
        ]

        # Отправляем в DataHub обновлённый аспект GlossaryTerms.
        mcp = MetadataChangeProposalWrapper(
            entityUrn=asset_urn,
            aspect=GlossaryTermsClass(
                terms=[
                    GlossaryTermAssociationClass(urn=urn)
                    for urn in remaining_urns
                ],
                auditStamp=AuditStampClass(
                    time=0, actor="urn:li:corpuser:datahub"
                ),
            ),
        )
        graph.emit_mcp(mcp)

        return {
            "action": action,
            "asset_urn": asset_urn,
            "removed_term_urn": REVENUE_GLOSSARY_URN,
            "status": "applied_to_datahub",
            "remaining_terms_count": len(remaining_urns),
        }
    else:
        raise ValueError(f"Неподдерживаемое действие изменения графа: {action}")


def check_and_invalidate_provenance(
    asset_urn: str, gms_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Наблюдатель изменений графа: проверяет рабочие метаданные DataHub для asset_urn.
    Если зависимости графа доказательств, лежащие в основе сохранённого Decision Provenance, изменились,
    меняет статус обоснования на 'stale' и сразу записывает обновление в DataHub.
    """
    target_gms_url = gms_url or os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
    graph = DataHubGraph(
        DataHubGraphConfig(
            server=target_gms_url,
            token=os.getenv("DATAHUB_GMS_TOKEN") or None,
        )
    )

    query = """
    query checkGraphState($urn: String!) {
      dataset(urn: $urn) {
        properties {
          name
          customProperties {
            key
            value
          }
        }
        glossaryTerms {
          terms {
            term {
              urn
            }
          }
        }
      }
    }
    """

    res = graph.execute_graphql(query, variables={"urn": asset_urn})
    dataset_data = res.get("dataset") if res else None
    if not dataset_data or not dataset_data.get("properties"):
        return {"error": f"Актив {asset_urn} не найден в DataHub"}

    props_list = dataset_data["properties"].get("customProperties") or []
    props_map = {item["key"]: item["value"] for item in props_list}

    current_status = props_map.get("eg_provenance_status", "unknown")
    decision_id = props_map.get("eg_decision_id", "unknown")

    # Проверяем текущие рабочие термины глоссария из графа DataHub.
    live_terms = [
        t["term"]["urn"]
        for t in dataset_data.get("glossaryTerms", {}).get("terms", [])
        if t.get("term")
    ]

    is_stale = False
    stale_reason = ""

    # Проверяем зависимость: связь с термином глоссария дохода.
    if REVENUE_GLOSSARY_URN not in live_terms:
        is_stale = True
        stale_reason = (
            f"Изменена зависимость графа доказательств: термин глоссария «Доход по классу клиента» "
            f"({REVENUE_GLOSSARY_URN}) удалён из актива."
        )

    if is_stale and current_status != "stale":
        # Обновляем пользовательские свойства в GMS DataHub.
        props_map["eg_provenance_status"] = "stale"
        props_map["eg_stale_reason"] = stale_reason

        asset_name = dataset_data["properties"].get("name") or "ORDER_DETAILS"

        mcp = MetadataChangeProposalWrapper(
            entityUrn=asset_urn,
            aspect=DatasetPropertiesClass(
                name=asset_name,
                customProperties=props_map,
            ),
        )
        graph.emit_mcp(mcp)

        return {
            "asset_urn": asset_urn,
            "decision_id": decision_id,
            "previous_status": current_status,
            "new_status": "stale",
            "stale_reason": stale_reason,
            "written_to_datahub": True,
        }

    return {
        "asset_urn": asset_urn,
        "decision_id": decision_id,
        "provenance_status": props_map.get("eg_provenance_status"),
        "stale_reason": props_map.get("eg_stale_reason"),
        "written_to_datahub": False,
    }
