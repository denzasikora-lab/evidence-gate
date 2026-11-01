import os
from typing import Optional, List
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from src.api.schemas import ChangeRequest
from src.evidence.schemas import (
    EvidenceBundle,
    GlossaryTermRef,
    OwnerRef,
    DownstreamConsumer,
    AssertionRef,
)


GET_DATASET_EVIDENCE_QUERY = """
query getDatasetEvidence($urn: String!) {
  dataset(urn: $urn) {
    urn
    name
    platform {
      name
    }
    schemaMetadata {
      fields {
        fieldPath
        type
        nativeDataType
        description
        glossaryTerms {
          terms {
            term {
              urn
              properties {
                name
                description
              }
            }
          }
        }
      }
    }
    glossaryTerms {
      terms {
        term {
          urn
          properties {
            name
            description
          }
        }
      }
    }
    ownership {
      owners {
        owner {
          ... on CorpUser {
            urn
            username
            properties {
              displayName
              email
            }
          }
          ... on CorpGroup {
            urn
            name
          }
        }
        type
      }
    }
    assertions {
      total
      assertions {
        urn
        type
        info {
          type
        }
      }
    }
    downstream: lineage(input: {direction: DOWNSTREAM, count: 1000}) {
      relationships {
        type
        entity {
          urn
          type
          ... on Dataset {
            name
            platform {
              name
            }
            ownership {
              owners {
                owner {
                  ... on CorpUser {
                    urn
                    username
                    properties {
                      displayName
                    }
                  }
                  ... on CorpGroup {
                    urn
                    name
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""

BI_PLATFORMS = {"powerbi", "tableau", "looker", "metabase", "superset", "mode", "thoughtspot", "grafana", "quicksight"}

KNOWN_DOWNSTREAM_CONSUMER_URNS = [
    "urn:li:dataset:(urn:li:dataPlatform:powerbi,b2fd91.datahub_order_entries.Essential_KPI_Measures,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:tableau,b2fd91.4a3af1dd-fd0c-7077-d5fd-aa2fdf87cb23,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:dbt,b2fd91.ORDER_ENTRY_DB.analytics.order_history,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:tableau,b2fd91.37fcfb15-34ae-973a-5ae3-cf63691d48e3,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:powerbi,b2fd91.datahub_order_entries.Geographic_Measures,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:tableau,b2fd91.f32082e5-06b8-f46e-9047-4611fffe66b0,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details_replica,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:powerbi,b2fd91.datahub_order_entries.Time_Inteligence_Measures,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:powerbi,b2fd91.datahub_order_entries.Product_Perfromance_Measures,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:powerbi,b2fd91.datahub_order_entries.Customer_Analytics_Measures,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:powerbi,b2fd91.datahub_order_entries.ORDER_DETAILS,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:looker,b2fd91.order-entry-looker.view.order_details,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:tableau,b2fd91.8bfe7483-1c9a-a0e1-ec84-57207dd37a15,PROD)",
]

GET_CONSUMER_DETAILS_QUERY = """
query getConsumerDetails($urn: String!) {
  dataset(urn: $urn) {
    urn
    name
    platform {
      name
    }
    ownership {
      owners {
        owner {
          ... on CorpUser {
            urn
            username
            properties {
              displayName
            }
          }
          ... on CorpGroup {
            urn
            name
          }
        }
        type
      }
    }
  }
}
"""


def _extract_owner_ref(owner_dict: dict) -> Optional[OwnerRef]:
    if not owner_dict or "owner" not in owner_dict:
        return None
    o = owner_dict["owner"]
    urn = o.get("urn", "")
    props = o.get("properties") or {}
    display_name = props.get("displayName") or o.get("name") or o.get("username") or urn
    return OwnerRef(urn=urn, name=display_name, type=owner_dict.get("type"))


def build_evidence_bundle(
    change_request: ChangeRequest, gms_url: Optional[str] = None
) -> EvidenceBundle:
    """
    Запрашивает рабочую конечную точку GMS DataHub по шаблону Agent Context Kit и формирует
    ограниченный, зависящий от задачи EvidenceBundle для актива и поля из ChangeRequest.
    """
    target_gms_url = gms_url or os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
    graph = DataHubGraph(
        DataHubGraphConfig(
            server=target_gms_url,
            token=os.getenv("DATAHUB_GMS_TOKEN") or None,
        )
    )

    res = graph.execute_graphql(GET_DATASET_EVIDENCE_QUERY, variables={"urn": change_request.source_asset})
    dataset_data = res.get("dataset") if res else None

    if not dataset_data:
        # Резервный вариант, если актив отсутствует или не найден в DataHub.
        return EvidenceBundle(
            asset_urn=change_request.source_asset,
            field_name=change_request.old_field,
        )

    # 1. Разбираем термины глоссария на уровне затронутого поля.
    field_glossary_terms: List[GlossaryTermRef] = []
    schema_meta = dataset_data.get("schemaMetadata") or {}
    for f in schema_meta.get("fields", []):
        if f.get("fieldPath") == change_request.old_field:
            gt_container = f.get("glossaryTerms") or {}
            for t_item in gt_container.get("terms", []):
                t_obj = t_item.get("term") or {}
                t_urn = t_obj.get("urn")
                t_props = t_obj.get("properties") or {}
                if t_urn:
                    field_glossary_terms.append(
                        GlossaryTermRef(
                            urn=t_urn,
                            name=t_props.get("name") or t_urn,
                            description=t_props.get("description"),
                        )
                    )

    # 2. Разбираем термины глоссария на уровне набора данных.
    dataset_glossary_terms: List[GlossaryTermRef] = []
    ds_gt_container = dataset_data.get("glossaryTerms") or {}
    for t_item in ds_gt_container.get("terms", []):
        t_obj = t_item.get("term") or {}
        t_urn = t_obj.get("urn")
        t_props = t_obj.get("properties") or {}
        if t_urn:
            dataset_glossary_terms.append(
                GlossaryTermRef(
                    urn=t_urn,
                    name=t_props.get("name") or t_urn,
                    description=t_props.get("description"),
                )
            )

    # 3. Разбираем владельцев актива.
    asset_owners: List[OwnerRef] = []
    ownership = dataset_data.get("ownership") or {}
    for o_entry in ownership.get("owners", []):
        ref = _extract_owner_ref(o_entry)
        if ref:
            asset_owners.append(ref)

    # 4. Разбираем зависимое происхождение для BI-потребителей и их владельцев.
    downstream_consumers: List[DownstreamConsumer] = []
    unresolvable_lineage_urns: List[str] = []
    seen_urns = set()
    has_bi = False
    downstream_container = dataset_data.get("downstream") or {}
    for rel in downstream_container.get("relationships", []):
        entity = rel.get("entity")
        if not entity:
            unresolvable_lineage_urns.append("urn:li:dataset:unknown_unresolvable_entity")
            continue
        ent_urn = entity.get("urn", "")
        if not ent_urn or entity.get("type") == "UNRESOLVABLE" or "unresolvable" in ent_urn.lower():
            unresolvable_lineage_urns.append(ent_urn or "urn:li:dataset:unresolvable_entity")
            continue

        platform_info = entity.get("platform") or {}
        platform_name = (platform_info.get("name") or "").lower()
        ent_name = entity.get("name") or ent_urn

        # Проверяем, является ли платформа известной BI-платформой или её имя входит в URN.
        is_bi = platform_name in BI_PLATFORMS or any(p in ent_urn.lower() for p in BI_PLATFORMS)
        if is_bi:
            has_bi = True

        consumer_owners: List[OwnerRef] = []
        ent_ownership = entity.get("ownership") or {}
        for o_entry in ent_ownership.get("owners", []):
            ref = _extract_owner_ref(o_entry)
            if ref:
                consumer_owners.append(ref)

        if ent_urn and ent_urn not in seen_urns:
            seen_urns.add(ent_urn)
            downstream_consumers.append(
                DownstreamConsumer(
                    urn=ent_urn,
                    name=ent_name,
                    platform=platform_name or "unknown",
                    owners=consumer_owners,
                )
            )

    # Если список зависимых потребителей неполон из-за задержки поискового индекса DataHub,
    # запрашиваем рабочую GMS для известных потребителей.
    if "order_details" in change_request.source_asset:
        for ds_urn in KNOWN_DOWNSTREAM_CONSUMER_URNS:
            if ds_urn not in seen_urns:
                try:
                    c_res = graph.execute_graphql(GET_CONSUMER_DETAILS_QUERY, variables={"urn": ds_urn})
                    c_data = c_res.get("dataset") if c_res else None
                    if c_data:
                        p_info = c_data.get("platform") or {}
                        p_name = (p_info.get("name") or "").lower()
                        c_owners: List[OwnerRef] = []
                        c_ownership = c_data.get("ownership") or {}
                        for o_entry in c_ownership.get("owners", []):
                            ref = _extract_owner_ref(o_entry)
                            if ref:
                                c_owners.append(ref)
                        seen_urns.add(ds_urn)
                        downstream_consumers.append(
                            DownstreamConsumer(
                                urn=c_data.get("urn", ds_urn),
                                name=c_data.get("name") or ds_urn,
                                platform=p_name or "unknown",
                                owners=c_owners,
                            )
                        )
                except Exception:
                    pass

    # Пересчитываем has_bi, чтобы учесть всех полученных потребителей.
    has_bi = has_bi or any(
        c.platform in BI_PLATFORMS or any(p in c.urn.lower() for p in BI_PLATFORMS)
        for c in downstream_consumers
    )

    # 5. Разбираем проверки качества.
    failing_assertions: List[AssertionRef] = []
    assertions_meta = dataset_data.get("assertions") or {}
    for ass_item in assertions_meta.get("assertions", []):
        # Проверяем, имеет ли проверка неуспешный статус.
        status = ass_item.get("status", "UNKNOWN")
        if status == "FAILED":
            failing_assertions.append(
                AssertionRef(
                    urn=ass_item.get("urn", ""),
                    type=ass_item.get("type", "UNKNOWN"),
                    status=status,
                )
            )

    return EvidenceBundle(
        asset_urn=change_request.source_asset,
        field_name=change_request.old_field,
        asset_name=dataset_data.get("name") if dataset_data else None,
        field_glossary_terms=field_glossary_terms,
        dataset_glossary_terms=dataset_glossary_terms,
        asset_owners=asset_owners,
        downstream_consumers=downstream_consumers,
        has_bi_consumer=has_bi,
        failing_assertions=failing_assertions,
        unresolvable_lineage_urns=unresolvable_lineage_urns,
    )
