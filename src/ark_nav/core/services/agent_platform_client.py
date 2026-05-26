"""智能体平台（Agent Platform）API 客户端。

负责所有与"智能体平台"相关的 HTTP 调用：
- 鉴权（auth token）
- RAG 检索（search_kb / fetch_rag）
- FAQ 知识库分页拉取（_get_faq_page_data）
- Table 知识库拉取（_get_faq_table_data）
- Prompt 模板查询（_get_prompt_by_name / init_prompt_from_agent_rag）

注意：和平安大模型平台（call_bigmodel_api）是完全独立的两个外部系统，
此模块不应该出现任何大模型 API 相关代码。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import httpx

from ark_nav.core.utils.agent_platform_config import AgentPfmConfig
from ark_nav.core.utils.http_client_manager import get_client
from ark_nav.core.utils.nav_logger import get_logger, print_execution_time

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# URL 构造
# ---------------------------------------------------------------------------


async def _get_kb_url() -> str:
    return f"{AgentPfmConfig.HOST}{AgentPfmConfig.RAG_QUERY_URL}"


async def _get_faq_page_url() -> str:
    return f"{AgentPfmConfig.HOST}{AgentPfmConfig.RAG_FAQ_PAGE_URL}"


async def _get_faq_page_similar_url() -> str:
    return f"{AgentPfmConfig.HOST}{AgentPfmConfig.RAG_FAQ_PAGE_SIMILAR_URL}"


async def _get_faq_table_detail_url() -> str:
    return f"{AgentPfmConfig.HOST}{AgentPfmConfig.RAG_FAQ_TABLE_DETAIL_URL}"


async def _get_faq_table_list_url() -> str:
    return f"{AgentPfmConfig.HOST}{AgentPfmConfig.RAG_FAQ_TABLE_LIST_URL}"


# ---------------------------------------------------------------------------
# 鉴权
# ---------------------------------------------------------------------------


@print_execution_time
async def _get_agent_auth_token(client: httpx.AsyncClient) -> str | None:
    auth_url = f"{AgentPfmConfig.HOST}{AgentPfmConfig.TOKEN_URL}"

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }

    payload = {
        "appId": AgentPfmConfig.TENANT_ID,
        "appSecret": AgentPfmConfig.APP_SEC,
    }

    logger.info("Calling agent platform to get auth token")
    try:
        logger.info(f"token_url:{auth_url}")
        response = await get_client().post(url=auth_url, headers=headers, json=payload, timeout=30)
        logger.info("succeed to get the auth token from agent platform")
        response.raise_for_status()
        response_json = response.json()
        if response_json.get("msg") == "success":
            return response_json.get("data")
        raise Exception(f"API call failed: {response_json.get('msg')}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {response}, error: {e}")
    except Exception as e:
        logger.error(f"API call failed: {e}", exc_info=True)
    return None


# ---------------------------------------------------------------------------
# RAG 检索（业务在线查询用）
# ---------------------------------------------------------------------------


async def _assemble_req_payload(
        query: str,
        score_threshold: float,
        top_n: int,
        kb_ids: List[str],
        kb_type: List[str],
        auth_token: str,
        tenant_id: str = "wfcz-yjdd",
        labels: List[str] = None,
) -> tuple[Dict[str, str], Dict[str, Any]]:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "auth-token": auth_token,
    }
    payload = {
        "tenantId": tenant_id,
        "content": query,
        "context": {
            "faqScoreLimit": score_threshold,
            "knIds": kb_ids,
            "dataTypeList": kb_type,
            "topN": top_n,
            "queryRewrite": 0,
        },
    }
    if labels and len(labels) > 0:
        payload['context']['property'] = {
            "fileds": [
                {
                    "name": "labels",
                    "value": labels,
                    "condition": "contains",
                }
            ]
        }
    return headers, payload


async def search_kb(
        query: str,
        kb_type: List[str],
        kb_ids: List[str],
        tenant_id: str = "wfcz-yjdd",
        score_threshold: float = 0.8,
        top_n: int = 1,
        labels: List[str] = None,
) -> List[Dict[str, Any]]:
    """调用智能体平台 RAG 检索接口，返回匹配的知识结果。"""
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
            labels=labels,
        )
        logger.info(f"payload={payload}")
        response = await get_client().post(
            url=rag_url,
            headers=headers,
            json=payload,
            timeout=30.0,
        )

        if response.status_code >= 400:
            logger.error(f"KB 服务返回错误: {response.status_code} - {response.text}")
            return [{"error": f"KB 服务错误: {response.status_code}", "details": response.text}]

        try:
            response_json = response.json()
            logger.info(f"raw response:{response_json}")
            return extract_answer(response_json)
        except Exception as e:
            logger.error(f"解析响应失败: {e}, 原始内容: {response.text}")
            return [{"error": "响应格式错误", "raw": response.text}]

    except Exception as e:
        logger.error(f"调用 KB 服务失败: {e}", exc_info=True)
        return [{"error": str(e)}]


def extract_answer(response_json: dict) -> List[Dict]:
    data = response_json.get("data")
    if response_json.get("code") != "200":
        logger.error(f"fail to fetch result from kb, resp:{response_json}")
        return []

    if not isinstance(data, list) or len(data) == 0:
        return []

    results = []
    for d in data:
        seg_content_str = d.get("segContent")
        data_type = d.get("dataType")
        seg = json.loads(seg_content_str)
        if data_type == "faq":
            results.append({"answer": seg.get("answer"), "score": d.get("score")})
        elif data_type == "table":
            results.append({"answer": seg, "score": d.get("score")})
    return results


async def fetch_rag(
    query: str,
    kb_type: List[str],
    kb_ids: List[str] = None,
    labels: List[str] = None,
    score_threshold: float = 0.9,
) -> str | Dict | None:
    """上层 RAG 查询包装：默认用 AgentPfmConfig.KG_ID。"""
    logger.info(f"fetch rag from KB,query={query}")
    answers = await search_kb(
        query=query,
        kb_type=kb_type,
        kb_ids=[AgentPfmConfig.KG_ID] if kb_ids is None else kb_ids,
        labels=labels,
        score_threshold=score_threshold,
    )
    logger.info(f"fetch rag from KB,result={answers}")
    if answers is not None and len(answers) > 0:
        return answers[0].get("answer")
    return None


# ---------------------------------------------------------------------------
# Prompt 模板加载（启动时调用）
# ---------------------------------------------------------------------------


async def _get_prompt_by_name(prompt_name: str) -> str | None:
    logger.info("Calling agent platform to get prompt template")
    try:
        agent_platform_kg_id = AgentPfmConfig.KG_ID
        answers = await search_kb(
            query=prompt_name,
            kb_type=["faq"],
            kb_ids=[agent_platform_kg_id],
        )
        if answers is not None and len(answers) > 0:
            return answers[0].get("answer")
        logger.warning(f"fail to load any prompt from kb by: {prompt_name}")
        return None
    except Exception as e:
        logger.error(f"调用 prompt 服务失败: {e}", exc_info=True)
        return None


@print_execution_time
async def init_prompt_from_agent_rag():
    """从智能体平台拉取 prompt 模板，写入 os.environ 供业务读取。"""
    logger.info("start loading ARK prompts")
    xiezhi_prompt = await _get_prompt_by_name("服务意图识别")
    baize_prompt = await _get_prompt_by_name("白泽意图重写")
    ylx_prompt = await _get_prompt_by_name("养老险意图识别")
    if xiezhi_prompt:
        os.environ["XIEZHI_PROMPT"] = xiezhi_prompt
        logger.info("load prompt for (服务意图识别) successfully!")
    if baize_prompt:
        os.environ["BAIZE_PROMPT"] = baize_prompt
        logger.info("load prompt for (白泽意图重写) successfully!")
    if ylx_prompt:
        os.environ["YLX_PROMPT"] = ylx_prompt
        logger.info("load prompt for (养老险意图识别) successfully!")


# ---------------------------------------------------------------------------
# FAQ 知识库分页拉取（建索引用）
# ---------------------------------------------------------------------------


@print_execution_time
async def _get_faq_page_data(
    kb_id: str,
    category_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """拉取 FAQ 知识库数据，支持按 categoryId 过滤。

    Args:
        kb_id: 知识库 ID（远程平台 knId）
        category_id: 目录 ID。传入则只拉该目录下的 FAQ（用于增量同步）；
                     None 表示拉取所有目录（全量同步）

    返回字典中**始终带 categoryId 字段**，用于本地按目录精准匹配/删除。
    """
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
            "auth-token": auth_token,
        }

        payload_template = {
            'tenantId': AgentPfmConfig.TENANT_ID,
            'userName': 'super-agent',
            'knId': kb_id,
            'pageSize': 500,
            'currentPage': 1,
        }
        # 增量同步：智能体平台 FAQ 接口支持按 categoryId 过滤
        if category_id:
            payload_template['categoryId'] = str(category_id)
            logger.info(f"_get_faq_page_data partial mode kb_id={kb_id} category_id={category_id}")
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
                            'tenantId': AgentPfmConfig.TENANT_ID,
                            'userName': 'super-agent',
                            'standardQid': standard_qid,
                            'pageSize': 500,
                            'currentPage': 1,
                        }
                        response_similar = await get_client().post(
                            url=faq_page_similar_url, headers=headers,
                            json=payload_similar, timeout=30,
                        )

                        if response_similar.status_code != 200:
                            logger.error(
                                f"获取标问{standard_question}的相似问请求失败，状态码: {response_similar.status_code}"
                            )
                            stop_outer_loop = True
                            break
                        data_similar = response_similar.json()
                        records_similar = data_similar.get("data", {}).get("records", [])
                        similar_questions = [sq.get("similarQuestion", "") for sq in records_similar]
                    else:
                        similar_questions = [sq.get("similarQuestion", "") for sq in similar_question_list]

                    answer = record.get("faqAnswer", {}).get("content", "")
                    category_name = record.get("categoryName", "")
                    record_category_id = str(record.get("categoryId", "") or "")
                    if status == "1":
                        for question in [standard_question] + similar_questions:
                            all_faq_data.append({
                                "text": question,
                                "answer": answer,
                                "categoryName": category_name,
                                "categoryId": record_category_id,
                                "status": status,
                                "kbType": "faq",
                                "kbLabel": "#".join(labels),
                            })

            unique_data = [dict(t) for t in set(tuple(d.items()) for d in all_faq_data)]
            return unique_data
        except Exception as e:
            logger.error(f"解析响应失败: {e}, 原始内容: {response.text}")
    except Exception as e:
        logger.error(f"API call failed: {e}", exc_info=True)
    return []


# ---------------------------------------------------------------------------
# Table 知识库拉取（建索引用）
# ---------------------------------------------------------------------------


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
            "auth-token": auth_token,
        }

        payload_template = {
            'tenantId': AgentPfmConfig.TENANT_ID,
            'userName': 'super-agent',
            'knId': kb_id,
            'pageSize': 500,
            'currentPage': 1,
        }

        payload = payload_template.copy()
        payload['currentPage'] = 1

        response_table_list = await get_client().post(
            url=faq_table_list_url, headers=headers, json=payload_template, timeout=30,
        )

        if response_table_list.status_code != 200:
            logger.error(f"FAQ PAGE 服务错误: {response_table_list.status_code} - {response_table_list.text}")
            return []

        try:
            stop_outer_loop = False
            faq_table_data = []
            response_json = response_table_list.json()
            table_list = response_json.get("data", {}).get("records", [])
            table_ids = [
                (str(t.get("id", "")), "#".join(label.get("name", "") for label in t.get("knLabelList", [])))
                for t in table_list if str(t.get("enable", "")) == "1"
            ]
            for table_id, labels in table_ids:
                if stop_outer_loop:
                    break
                payload['tableId'] = table_id
                response_table_detail = await get_client().post(
                    url=faq_table_detail_url, headers=headers, json=payload, timeout=30,
                )

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
                    response = await get_client().post(
                        url=faq_table_detail_url, headers=headers, json=payload, timeout=30,
                    )

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


def main():
    import asyncio
    result = asyncio.run(_get_faq_table_data(AgentPfmConfig.KG_ID))
    logger.info(f"=========={len(result)}==========")
    for item in result[:5]:
        print(item)


if __name__ == '__main__':
    main()
