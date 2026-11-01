#!/usr/bin/env python3
"""
Verification script connecting to DataHub MCP / GMS Server.
Retrieves the revenue-bearing dataset from showcase-ecommerce:
urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)
which contains the revenue-bearing `order_total` field, linked glossary terms ('Order Total', 'Revenue by Customer Class'),
owners (David Kim, Julia Novak), and downstream BI dashboards (PowerBI, Tableau, Looker).
"""
import os
import json
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig

DATAHUB_GMS_URL = os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")


def verify_mcp_connection():
    print(f"Connecting to DataHub GMS at {DATAHUB_GMS_URL}...")
    graph = DataHubGraph(
        DataHubGraphConfig(
            server=DATAHUB_GMS_URL,
            token=os.getenv("DATAHUB_GMS_TOKEN") or None,
        )
    )

    dataset_urn = "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)"

    query = """
    query getDatasetDetails($urn: String!) {
      dataset(urn: $urn) {
        urn
        type
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
          }
        }
        fineGrainedLineages {
          transformOperation
          upstreams {
            urn
          }
          downstreams {
            urn
          }
        }
        downstreamLineage: lineage(input: {direction: DOWNSTREAM}) {
          relationships {
            type
            entity {
              urn
              type
            }
          }
        }
        upstreamLineage: lineage(input: {direction: UPSTREAM}) {
          relationships {
            type
            entity {
              urn
              type
            }
          }
        }
      }
    }
    """

    res = graph.execute_graphql(query, variables={"urn": dataset_urn})
    print(json.dumps(res, indent=2))
    return res


if __name__ == "__main__":
    verify_mcp_connection()
