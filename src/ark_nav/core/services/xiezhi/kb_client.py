"""智能体平台知识库（KB）客户端。

从 xiezhi_http.py 拆分而来（2026-05），保持原函数签名与逻辑一字不改。

包含：
- URL helper：_get_kb_url, _get_faq_page_url, _get_faq_page_similar_url,
              _get_faq_table_detail_url, _get_faq_table_list_url
- 请求组装：_assemble_req_payload
- 主查询：search_kb（外部公开）, fetch_rag（外部公开）
- 响应解析：extract_answer
- 全量拉取：_get_faq_page_data, _get_faq_table_data
"""
import json
from typing import List, Optional, Dict, Any

from ark_nav.core.services.xiezhi.auth import _get_agent_auth_token
from ark_nav.core.utils.agent_platform_config import AgentPlatformConfig
from ark_nav.core.utils.http_client_manager import get_client
from ark_nav.core.utils.nav_logger import get_logger, print_execution_time

logger = get_logger(__name__)


async def _assemble_req_payload(
        query: str,
        score_threshold: float,
        top_n: int,
        kb_ids: List[str],
        kb_type: List[str],
        auth_token: str,
        tenant_id: str = "wfcz-yjdd",
        labels: List[str] = None
) -> tuple[Dict[str, str], Dict[str, Any]]:
    """
    组装请求头和请求体。

    Args:
        query: 用户输入问题
        score_threshold: 相似度阈值
        top_n: 返回前 N 个结果
        kb_ids: 知识库 ID 列表
        kb_type: 知识库类型（如 faq）
        auth_token: 认证 token
        tenant_id: 租户 ID

    Returns:
        headers, payload: 请求头和请求体
    """
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "auth-token": auth_token
    }
    payload = {
        "tenantId": tenant_id,
        "content": query,
        "context": {
            "faqScoreLimit": score_threshold,
            "knIds": kb_ids,
            "dataTypeList": kb_type,
            "topN": top_n,
            "queryRewrite": 0
        }
    }
    if labels and len(labels) > 0:
        # pass
        payload['context']['property'] = {
            "fileds": [
                {
                    "name": "labels",
                    "value": labels,
                    "condition": "contains"
                }
            ]
        }
    return headers, payload


async def _get_kb_url() -> str:
    """
    构建 KB 服务的完整 URL。
    """
    return f"{AgentPlatformConfig.HOST}{AgentPlatformConfig.RAG_QUERY_URL}"


async def _get_faq_page_url() -> str:
    """
    构建 FAQ PAGE 服务的完整 URL。
    """
    return f"{AgentPlatformConfig.HOST}{AgentPlatformConfig.RAG_FAQ_PAGE_URL}"


async def _get_faq_page_similar_url() -> str:
    """
    构建 FAQ PAGE SIMILAR 服务的完整 URL。
    """
    return f"{AgentPlatformConfig.HOST}{AgentPlatformConfig.RAG_FAQ_PAGE_SIMILAR_URL}"


async def _get_faq_table_detail_url() -> str:
    """
    构建 FAQ TABLE DETAIL 服务的完整 URL。
    """
    return f"{AgentPlatformConfig.HOST}{AgentPlatformConfig.RAG_FAQ_TABLE_DETAIL_URL}"


async def _get_faq_table_list_url() -> str:
    """
    构建 FAQ TABLE LIST 服务的完整 URL。
    """
    return f"{AgentPlatformConfig.HOST}{AgentPlatformConfig.RAG_FAQ_TABLE_LIST_URL}"


async def search_kb(
        query: str,
        kb_type: List[str],
        kb_ids: List[str],
        tenant_id: str = "wfcz-yjdd",
        score_threshold: float = 0.8,
        top_n: int = 1,
        labels: List[str] = None
) -> List[Dict[str, Any]]:
    """
    调用 KB 服务，获取知识库匹配结果。

    Args:
        query: 用户输入问题
        kb_type: 知识库类型（如 faq）
        kb_ids: 知识库 ID 列表
        tenant_id: 租户 ID（默认 wfcz-yjdd）
        score_threshold: 相似度阈值（默认 0.85）
        top_n: 返回结果数量（默认 3）
        labels: 知识库标签列表

    Returns:
        响应 JSON 或错误信息
    """
    try:
        rag_url = await _get_kb_url()

        auth_token = await _get_agent_auth_token(get_client())
        if auth_token is None:
            logger.error("Failed to get auth token from agent platform")
            return [{"error": "Auth token missing", "code": 401}]

        headers, payload = await _assemble_req_payload(
            query=query,
            score_threshold=score_threshold,
            top_n=top_n,
            kb_ids=kb_ids,
            kb_type=kb_type,
            auth_token=auth_token,
            tenant_id=tenant_id,
            labels=labels
        )
        logger.info(f"payload={payload}")
        response = await get_client().post(
            url=rag_url,
            headers=headers,
            json=payload,
            timeout=30.0
        )

        # 检查状态码
        if response.status_code >= 400:
            logger.error(f"KB 服务返回错误: {response.status_code} - {response.text}")
            return [{"error": f"KB 服务错误: {response.status_code}", "details": response.text}]

        try:
            response_json = response.json()
            logger.info(f"raw response:{response_json}")
            response = extract_answer(response_json)
            return response
        except Exception as e:
            logger.error(f"解析响应失败: {e}, 原始内容: {response.text}")
            return [{"error": "响应格式错误", "raw": response.text}]

    except Exception as e:
        logger.error(f"调用 KB 服务失败: {e}", exc_info=True)
        return [{"error": str(e)}]


def extract_answer(response_json: dict) -> List[Dict]:
    data = response_json.get("data")
    # 检查 code 是否为 200
    if response_json.get("code") != "200":
        logger.error(f"fail to fetch result from kb, resp:{response_json}")
        return []

    if not isinstance(data, list) or len(data) == 0:
        return []

    # 3. 获取第一个元素，必须是 dict
    results = []
    for d in data:
        seg_content_str = d.get("segContent")
        data_type = d.get("dataType")
        seg = json.loads(seg_content_str)
        if data_type == "faq":
            results.append({
                "answer": seg.get("answer"),
                "score": d.get("score")
            })
        elif data_type == "table":
            results.append({
                "answer": seg,
                "score": d.get("score")
            })
    return results


@print_execution_time
async def _get_faq_page_data(kb_id: str) -> List[Dict[str, Any]]:
    try:
        faq_page_url = await _get_faq_page_url()
        faq_page_similar_url = await _get_faq_page_similar_url()
        auth_token = await _get_agent_auth_token(get_client())
        if auth_token is None:
            logger.error("Failed to get auth token from agent platform")
            return []

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Connection": "keep-alive",
            "auth-token": auth_token
        }

        payload_template = {
            'tenantId': AgentPlatformConfig.TENANT_ID,
            'userName': 'super-agent',
            'knId': kb_id,
            'pageSize': 500,
            'currentPage': 1
        }
        payload = payload_template.copy()
        payload['currentPage'] = 1

        response = await get_client().post(url=faq_page_url, headers=headers, json=payload, timeout=30)
        if response.status_code != 200:
            logger.error(f"FAQ PAGE 服务返回错误: {response.status_code} - {response.text}")
            return []

        try:
            stop_outer_loop = False
            all_faq_data = []
            response_json = response.json()
            total = response_json.get("data", {}).get("total", 0)
            pages = response_json.get("data", {}).get("pages", 0)
            logger.info(f"调用 FAQ PAGE 总记录数为:{total}，共{pages}页")
            for page in range(1, pages + 1):
                if stop_outer_loop:
                    break
                logger.info(f"正在获取第 {page} 页数据...")
                payload['currentPage'] = page
                response_standard = await get_client().post(url=faq_page_url, headers=headers, json=payload, timeout=30)
                if response_standard.status_code != 200:
                    logger.error(f"第 {page} 页请求失败，状态码: {response_standard.status_code}")
                    break
                data_standard = response_standard.json()
                records = data_standard.get("data", {}).get("records", [])
                for record in records:
                    standard_question = record.get("standardQuestion", "")
                    status = str(record.get("status", ""))
                    standard_qid = record.get("faqAnswer", {}).get("standardQid", 0)
                    similar_count = record.get("similarCount", 0)
                    similar_question_list = record.get("similarQuestionList", [])
                    kn_label_list = record.get("knLabelList", [])
                    labels = [kn_label.get("name", "") for kn_label in kn_label_list if kn_label.get("name", "")]
                    if similar_count > len(similar_question_list):
                        payload_similar = {
                            'tenantId': AgentPlatformConfig.TENANT_ID,
                            'userName': 'super-agent',
                            'standardQid': standard_qid,
                            'pageSize': 500,
                            'currentPage': 1
                        }
                        response_similar = await get_client().post(url=faq_page_similar_url, headers=headers,
                                                                   json=payload_similar, timeout=30)

                        if response_similar.status_code != 200:
                            logger.error(
                                f"获取标问{standard_question}的相似问请求失败，状态码: {response_similar.status_code}")
                            stop_outer_loop = True
                            break
                        data_similar = response_similar.json()
                        records_similar = data_similar.get("data", {}).get("records", [])
                        similar_questions = [sq.get("similarQuestion", "") for sq in records_similar]
                    else:
                        similar_questions = [sq.get("similarQuestion", "") for sq in similar_question_list]

                    # 提取答案
                    answer = record.get("faqAnswer", {}).get("content", "")
                    # 提取分类
                    category_name = record.get("categoryName", "")
                    # 将标准问题和相似问题合并为多个问答对
                    if status == "1":
                        for question in [standard_question] + similar_questions:
                            all_faq_data.append({
                                "text": question,
                                "answer": answer,
                                "categoryName": category_name,
                                "status": status,
                                "kbType": "faq",
                                "kbLabel": "#".join(labels)
                            })

            unique_data = [dict(t) for t in set(tuple(d.items()) for d in all_faq_data)]
            return unique_data
        except Exception as e:
            logger.error(f"解析响应失败: {e}, 原始内容: {response.text}")
    except Exception as e:
        logger.error(f"API call failed: {e}", exc_info=True)
    return []


@print_execution_time
async def _get_faq_table_data(kb_id: str) -> List[Dict[str, Any]]:
    try:
        faq_table_list_url = await _get_faq_table_list_url()
        faq_table_detail_url = await _get_faq_table_detail_url()
        auth_token = await _get_agent_auth_token(get_client())
        if auth_token is None:
            logger.error("Failed to get auth token from agent platform")
            return []

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Connection": "keep-alive",
            "auth-token": auth_token
        }

        payload_template = {
            'tenantId': AgentPlatformConfig.TENANT_ID,
            'userName': 'super-agent',
            'knId': kb_id,
            'pageSize': 500,
            'currentPage': 1
        }

        payload = payload_template.copy()
        payload['currentPage'] = 1

        response_table_list = await get_client().post(url=faq_table_list_url, headers=headers, json=payload_template,
                                                      timeout=30)

        if response_table_list.status_code != 200:
            logger.error(f"FAQ PAGE 服务错误: {response_table_list.status_code} - {response_table_list.text}")
            return []

        try:
            stop_outer_loop = False
            faq_table_data = []
            response_json = response_table_list.json()
            table_list = response_json.get("data", {}).get("records", [])
            table_ids = [(str(t.get("id", "")), "#".join(label.get("name", "") for label in t.get("knLabelList", []))) for t in table_list if str(t.get("enable", "")) == "1"]
            for table_id, labels in table_ids:
                if stop_outer_loop:
                    break
                payload['tableId'] = table_id
                response_table_detail = await get_client().post(url=faq_table_detail_url, headers=headers, json=payload,
                                                                timeout=30)

                if response_table_detail.status_code != 200:
                    logger.error(f"获取表格{table_id}的请求失败，状态码: {response_table_detail.status_code}")
                    break
                data_table_detail = response_table_detail.json()
                total = data_table_detail.get("data", {}).get("total", 0)
                pages = data_table_detail.get("data", {}).get("pages", 0)
                logger.info(f"调用 FAQ PAGE TABLE DETAIL总记录数为:{total}，共{pages}页")
                for page in range(1, pages + 1):
                    logger.info(f"正在获取第 {page} 页数据...")
                    payload['currentPage'] = page
                    response = await get_client().post(url=faq_table_detail_url, headers=headers, json=payload,
                                                       timeout=30)

                    if response.status_code != 200:
                        logger.error(f"第 {page} 页请求失败，状态码: {response.status_code}")
                        stop_outer_loop = True
                        break

                    data = response.json()
                    records = data.get("data", {}).get("records", [])
                    for record in records:
                        origin_data = record.get("originData", {})
                        if origin_data:
                            if "sub_category_i" in origin_data:
                                origin_data["text"] = origin_data.pop("sub_category_i")
                            origin_data["kbType"] = "table"
                            origin_data["kbLabel"] = labels
                            faq_table_data.append(origin_data)

            return faq_table_data
        except Exception as e:
            logger.error(f"解析响应失败: {e}, 原始内容: {response_table_list.text}")
    except Exception as e:
        logger.error(f"API call failed: {e}", exc_info=True)
    return []


async def fetch_rag(query: str, kb_type: List[str], kb_ids: List[str] = None, labels: List[str] = None,
                    score_threshold: float = 0.9) -> str | Dict | None:
    logger.info(f"fetch rag from KB,query={query}")
    answers = await search_kb(
        query=query,
        kb_type=kb_type,
        kb_ids=[AgentPlatformConfig.KG_ID] if kb_ids is None else kb_ids,
        labels=labels,
        score_threshold=score_threshold
    )
    logger.info(f"fetch rag from KB,result={answers}")
    if answers is not None and len(answers) > 0:
        return answers[0].get("answer")
    return None
