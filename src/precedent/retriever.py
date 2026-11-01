import os
import sys
import json
from typing import Dict, Any, List, Optional, Tuple
from dotenv import load_dotenv
from google import genai
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from src.api.schemas import ChangeRequest

load_dotenv()


def narrate_precedent_comparison(
    applies_list: List[str],
    differs_list: List[str],
    candidate_id: str,
    prior_id: str,
) -> Tuple[List[str], List[str]]:
    """
    Использует Gemini LLM, чтобы естественно перефразировать детерминированные факты сравнения прецедентов.
    Возвращает детерминированные списки шаблонов, если GEMINI_API_KEY отсутствует или вызов API не удался.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        warning_msg = (
            "[LLM_UNAVAILABLE] Используется шаблонное сравнение прецедентов — "
            "вызов Gemini не выполнен: переменная окружения GEMINI_API_KEY не задана."
        )
        print(warning_msg, file=sys.stderr)
        return applies_list, differs_list

    try:
        client = genai.Client(api_key=api_key)
        prompt = f"""
Вы — Evidence Gate, автоматизированный механизм управления данными.
Перефразируйте эти детерминированные факты сравнения прецедентов для кандидатного Change Request '{candidate_id}' и предыдущего решения '{prior_id}'.

ДЕТЕРМИНИРОВАННЫЕ ФАКТЫ (ФИКСИРОВАНЫ — НЕ МЕНЯЙТЕ И НЕ ОПУСКАЙТЕ):
Что по-прежнему применимо:
{json.dumps(applies_list, indent=2)}

Что отличается:
{json.dumps(differs_list, indent=2)}

ИНСТРУКЦИИ:
1. Перефразируйте пункты разделов «Что по-прежнему применимо» и «Что отличается» в профессиональные предложения на русском языке.
2. Верните корректный JSON-объект РОВНО с двумя ключами: "what_still_applies" (список строк) и "what_differs" (список строк).
3. Не добавляйте, не удаляйте и не меняйте исходные факты или результаты решений.
4. Не используйте слова 'executive', «руководящий» и «исполнительный дашборд».
"""
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
        )
        text = response.text.strip() if response and response.text else ""
        if text.startswith("```json"):
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif text.startswith("```"):
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

        parsed = json.loads(text)
        new_applies = parsed.get("what_still_applies", applies_list)
        new_differs = parsed.get("what_differs", differs_list)
        if isinstance(new_applies, list) and isinstance(new_differs, list):
            for item in new_applies + new_differs:
                item_lower = str(item).lower()
                if "executive" in item_lower or "exec dashboard" in item_lower:
                    warning_msg = (
                        "[LLM_HALLUCINATION_DETECTED] В сравнении прецедентов Gemini упомянута запрещённая фраза 'executive' — используется шаблон."
                    )
                    print(warning_msg, file=sys.stderr)
                    return applies_list, differs_list
            return new_applies, new_differs
        else:
            raise ValueError("Gemini вернула недопустимую структуру JSON")
    except Exception as e:
        warning_msg = (
            f"[LLM_UNAVAILABLE] Используется шаблонное сравнение прецедентов — вызов Gemini не выполнен: {e}"
        )
        print(warning_msg, file=sys.stderr)
        return applies_list, differs_list


def find_precedent_decisions(
    change_request: ChangeRequest, gms_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Механизм поиска прецедентов: ищет в рабочем графе DataHub прежние артефакты Decision Provenance,
    повторно использует релевантные доказательства и формирует явное сравнение «Что применимо / Что отличается».
    """
    target_gms_url = gms_url or os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
    graph = DataHubGraph(
        DataHubGraphConfig(
            server=target_gms_url,
            token=os.getenv("DATAHUB_GMS_TOKEN") or None,
        )
    )

    # Ищем все наборы данных DataHub с пользовательскими свойствами.
    query = """
    query searchPrecedents {
      search(input: {type: DATASET, query: "*", count: 20}) {
        searchResults {
          entity {
            urn
            ... on Dataset {
              name
              properties {
                customProperties {
                  key
                  value
                }
              }
            }
          }
        }
      }
    }
    """

    res = graph.execute_graphql(query)
    results = (
        res.get("search", {}).get("searchResults", []) if res else []
    )

    # Если индекс поиска графа не построен, используем резервный прямой запрос GMS к набору данных.
    if not results:
        direct_query = """
        query getDatasetPrecedentDirect($urn: String!) {
          dataset(urn: $urn) {
            urn
            name
            properties {
              customProperties {
                key
                value
              }
            }
          }
        }
        """
        for known_urn in [
            "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)",
            "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details_replica,PROD)",
        ]:
            try:
                d_res = graph.execute_graphql(direct_query, variables={"urn": known_urn})
                d_obj = d_res.get("dataset") if d_res else None
                if d_obj:
                    results.append({"entity": d_obj})
            except Exception:
                pass

    found_precedents: List[Dict[str, Any]] = []

    for item in results:
        entity = item.get("entity") or {}
        props = (entity.get("properties") or {}).get("customProperties") or []
        props_map = {p["key"]: p["value"] for p in props}

        if "eg_decision_id" in props_map:
            prior_id = props_map.get("eg_decision_id")
            prior_asset = entity.get("urn")
            prior_status = props_map.get("eg_status")
            prior_risk = props_map.get("eg_risk_score")
            prior_rationale = props_map.get("eg_business_rationale")
            prior_url = props_map.get("eg_change_url")

            # Определяем детали сравнения.
            applies_list = []
            differs_list = []

            # 1. Проверка семантического расхождения.
            if (
                change_request.old_field == "order_total"
                and change_request.new_field == "recognized_revenue"
            ):
                applies_list.append(
                    "Одинаковое семантическое расхождение при переименовании поля: метрика валовых транзакций ('order_total') -> чистая метрика ('recognized_revenue')."
                )
                applies_list.append(
                    "Применимы определение термина глоссария дохода и порог расхождения агрегатов (1,00%)."
                )

            # 2. Сравнение активов.
            if prior_asset == change_request.source_asset:
                applies_list.append("Тот же URN целевого актива и путь происхождения набора данных.")
            else:
                differs_list.append(
                    f"Другой целевой актив: кандидат '{change_request.source_asset}', прежний '{prior_asset}'."
                )

            # 3. Сравнение ID изменения и URL запроса на слияние.
            differs_list.append(
                f"ID запроса на изменение: '{change_request.change_id}', прежний: '{prior_id}'."
            )
            if prior_url != change_request.pr_url:
                differs_list.append(
                    f"URL запроса на слияние: '{change_request.pr_url}', прежний: '{prior_url}'."
                )

            # Используем LLM для формулировок сравнения прецедентов с резервным шаблоном.
            applies_list, differs_list = narrate_precedent_comparison(
                applies_list, differs_list, change_request.change_id, prior_id
            )

            found_precedents.append(
                {
                    "precedent_decision_id": prior_id,
                    "prior_asset_urn": prior_asset,
                    "prior_status": prior_status,
                    "prior_risk_score": prior_risk,
                    "prior_rationale": prior_rationale,
                    "what_still_applies": applies_list,
                    "what_differs": differs_list,
                    "reused_evidence": [
                        "Определение термина глоссария дохода",
                        "Шаблон запроса исключения налогов и статусов при переходе от валовой к чистой сумме",
                        "Порог допустимого отклонения проверки 1,00%",
                    ],
                }
            )

    return {
        "candidate_change_id": change_request.change_id,
        "candidate_source_asset": change_request.source_asset,
        "precedents_found_count": len(found_precedents),
        "precedents": found_precedents,
    }
