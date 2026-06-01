# 环境变量配置

本文档列出 **业务代码（Python）实际读取的全部环境变量**。
公司基础设施（监控 agent / 日志采集 / Ray 框架自身）所需的变量不在此列，由运维侧自行管理。

> 通过 `.env` 文件（开发）或容器环境变量（生产）注入。
> **必填项缺失会导致服务启动失败**。可选项缺失会使用代码内置默认值。
>
> 复制 `.env.sample` 为 `.env` 后按下表填写。

## 目录

1. [平安大模型平台](#1-平安大模型平台)
2. [智能体平台](#2-智能体平台)
3. [知识库（KnowledgeBase）](#3-知识库knowledgebase)
4. [Ray Serve 副本配置](#4-ray-serve-副本配置)
5. [寿险红利渠道（ESG Bonus）](#5-寿险红利渠道esg-bonus)
6. [养老险一键场景 / 小安机器人（ESG）](#6-养老险一键场景--小安机器人esg)
7. [最小启动示例](#最小启动示例)

---

## 1. 平安大模型平台

调用平安 Qwen / OpenAI 等大模型时使用。来源：`src/ark_nav/core/utils/llm_platform_config.py`、`src/ark_nav/core/services/llm_platform_client.py`

| 变量名 | 必填 | 默认值 | 示例 | 说明 |
|---|---|---|---|---|
| `OPEN_AI_URL` | **是** | 无 | `http://eagw-gateway-sf.paic.com.cn:80/pingan/bigModel/api/v1/chat/completions` | 大模型 API 完整 URL |
| `RSA_PK` | **是** | 无 | `-----BEGIN PRIVATE KEY-----...` | RSA 私钥（OpenAPI 签名） |
| `CRE_ID` | **是** | 无 | `abc123-uuid` | OpenAPI 凭据 ID（`openApiCredential` 请求头） |
| `OPEN_API_CODE` | **是** | 无 | `arknav_v1` | OpenAPI 业务码（`openApiCode` 请求头） |
| `APP_KEY` | **是** | 无 | `Ym5NPfPrgp8sZ8LkcpR5...` | 寿险默认应用 key（GPT 签名用） |
| `APP_SECRET` | **是** | 无 | `OYqUvt8RNtvW7DqPDqM8...` | 寿险默认应用 secret（GPT 签名用） |
| `SCENE_ID` | **是** | 无 | `customer_service` | 寿险默认意图识别场景 ID |
| `INTENT_REWRITE_SCENE_ID` | **是** | 无 | `intent_rewrite_001` | 意图重写场景 ID（白泽） |
| `INTENT_REWRITE_APP_KEY` | **是** | 无 | `xxx` | 意图重写应用 key |
| `INTENT_REWRITE_APP_SECRET` | **是** | 无 | `xxx` | 意图重写应用 secret |
| `YLX_LLM_APP_KEY` | **是** | 无 | `xxx` | 养老险大模型应用 key |
| `YLX_LLM_APP_SECRET` | **是** | 无 | `xxx` | 养老险大模型应用 secret |
| `YLX_LLM_SCENE_ID` | **是** | 无 | `ylx_intent_001` | 养老险大模型场景 ID |

---

## 2. 智能体平台

调用智能体平台 RAG / FAQ / Table 接口时使用。来源：`src/ark_nav/core/utils/agent_platform_config.py`、`src/ark_nav/core/services/agent_platform_client.py`

| 变量名 | 必填 | 默认值 | 示例 | 说明 |
|---|---|---|---|---|
| `AGENT_PLATFORM_HOST` | **是** | 无 | `https://sa-agents-gateway-stg1.paic.com.cn` | 智能体平台域名（不含 path） |
| `AGENT_PLATFORM_TOKEN_URL` | **是** | 无 | `/appid/auth/login` | 鉴权接口路径 |
| `AGENT_PLATFORM_APP_ID` | **是** | 无 | `wfcz-yjdd` | 应用 ID（tenant ID） |
| `AGENT_PLATFORM_APP_SECRET` | **是** | 无 | `xxx` | 应用 secret |
| `AGENT_PLATFORM_KG_ID` | **是** | 无 | `4386` | 默认知识库 ID（养老险用 + RAG 通用查询用） |
| `AGENT_PLATFORM_RAG_QUERY_URL` | **是** | 无 | `/api/open/kn/knSearch` | RAG 检索接口路径 |
| `AGENT_PLATFORM_RAG_FAQ_PAGE_URL` | **是** | 无 | `/api/open/kn/faq/page` | FAQ 分页接口路径 |
| `AGENT_PLATFORM_RAG_FAQ_PAGE_SIMILAR_URL` | **是** | 无 | `/api/open/kn/faq/pageSimilar` | FAQ 相似问接口路径 |
| `AGENT_PLATFORM_RAG_FAQ_TABLE_LIST_URL` | **是** | 无 | `/api/open/kn/tableList` | Table 列表接口路径 |
| `AGENT_PLATFORM_RAG_FAQ_TABLE_DETAIL_URL` | **是** | 无 | `/api/open/kn/v2/tableDetailList` | Table 详情接口路径 |

---

## 3. 知识库（KnowledgeBase）

控制本地索引模式和同步策略。来源：`src/ark_nav/core/utils/kb_config.py`

| 变量名 | 必填 | 默认值 | 示例 | 说明 |
|---|---|---|---|---|
| `KB_MODE` | 否 | `local` | `local` / `remote` | 知识库模式。`local`=本地 FAISS 索引；`remote`=远程 REST API（紧急回滚用） |
| `KB_FULL_SYNC_TIME` | 否 | `21:30` | `21:30` | 每日全量同步时间（HH:MM 24 小时制） |
| `KB_PARTIAL_SYNC_INTERVAL_MINUTES` | 否 | `30` | `30` | 增量同步间隔（分钟） |
| `KB_PARTIAL_FAQ_CATEGORY_ID` | 否 | `""` | `26687` | 增量同步的 FAQ 目录 ID（远程平台 categoryId）。空字符串=禁用增量同步 |
| `SHOUXIAN_AGENT_PLATFORM_KG_ID` | **条件** | 无 | `4032` | 寿险知识库 ID。`KB_MODE=local` 时**必填** |

> `AGENT_PLATFORM_KG_ID`（养老险知识库 ID）在第 2 节列出——`KB_MODE=local` 时同样必填。

---

## 4. Ray Serve 副本配置

每个 Deployment 的副本数。来源：各 Deployment 文件模块级常量。

| 变量名 | 必填 | 默认值 | 示例 | 说明 |
|---|---|---|---|---|
| `API_REPLICAS` | 否 | `3` | `3` | FastAPI 网关副本数（固定，不弹性） |
| `EMBEDDING_MIN_REPLICAS` | 否 | `2` | `2` | Embedding 模型最小副本数（GPU 副本，所有 Agent 共享） |
| `EMBEDDING_MAX_REPLICAS` | 否 | `4` | `4` | Embedding 模型最大副本数 |
| `SHOUXIAN_AGENT_MIN_REPLICAS` | 否 | `3` | `3` | 寿险 Agent 最小副本数 |
| `SHOUXIAN_AGENT_MAX_REPLICAS` | 否 | `16` | `16` | 寿险 Agent 最大副本数（应对大促） |
| `YLX_AGENT_MIN_REPLICAS` | 否 | `1` | `1` | 养老险 Agent 最小副本数 |
| `YLX_AGENT_MAX_REPLICAS` | 否 | `4` | `4` | 养老险 Agent 最大副本数 |

> 这些变量**只在副本启动时生效**，运行时修改需要重启服务。

---

## 5. 寿险红利渠道（ESG Bonus）

寿险红利接口对接 ESG。来源：`src/ark_nav/domains/shouxian/services/shouxian_nav_service.py`

| 变量名 | 必填 | 默认值 | 示例 | 说明 |
|---|---|---|---|---|
| `ESG_BONUS_CHAT_ADDR` | **是** | 无 | `https://xx/bonus/chat?token={access_token}` | 红利接口地址，含 `{access_token}` 占位符 |
| `ESG_CLIENT_ID_4_BONUS` | **是** | 无 | `xxx` | Bonus 渠道 client ID |
| `ESG_CLIENT_SECRET_4_BONUS` | **是** | 无 | `xxx` | Bonus 渠道 client secret |
| `ESG_GRANT_TYPE_4_BONUS` | **是** | 无 | `client_credentials` | OAuth2 授权类型 |

---

## 6. 养老险一键场景 / 小安机器人（ESG）

养老险一键卡片对接小安机器人。来源：`src/ark_nav/domains/yanglaoxian/services/onekey_service.py`

| 变量名 | 必填 | 默认值 | 示例 | 说明 |
|---|---|---|---|---|
| `ESG_OAUTH_URL` | **是** | 无 | `https://xx/oauth/token` | ESG OAuth2 鉴权 URL |
| `ESG_CLIENT_ID` | **是** | 无 | `xxx` | ESG 客户端 ID |
| `ESG_CLIENT_SECRET` | **是** | 无 | `xxx` | ESG 客户端 secret |
| `ESG_GRANT_TYPE` | **是** | 无 | `client_credentials` | OAuth2 授权类型 |
| `ESG_XIAOAN_CHAT_ADDR` | **是** | 无 | `https://xx/xiaoan/chat?token={access_token}` | 小安聊天接口地址，含 `{access_token}` 占位符 |
| `ESG_TOKEN_EXPIRY` | **是** | 无 | `30` | ESG token 有效期（天） |
| `XIAOAN_REPOSITORY_ID` | **是** | 无 | `xxx` | 小安知识库 ID |

---

## 最小启动示例

```bash
# 平安大模型（必填）
OPEN_AI_URL=http://eagw-gateway-sf.paic.com.cn:80/pingan/bigModel/api/v1/chat/completions
RSA_PK=<your_rsa_private_key>
CRE_ID=<your_cre_id>
OPEN_API_CODE=<your_open_api_code>
APP_KEY=<your_app_key>
APP_SECRET=<your_app_secret>
SCENE_ID=<your_scene_id>
INTENT_REWRITE_SCENE_ID=<your_intent_rewrite_scene_id>
INTENT_REWRITE_APP_KEY=<your_intent_rewrite_app_key>
INTENT_REWRITE_APP_SECRET=<your_intent_rewrite_app_secret>
YLX_LLM_APP_KEY=<your_ylx_llm_app_key>
YLX_LLM_APP_SECRET=<your_ylx_llm_app_secret>
YLX_LLM_SCENE_ID=<your_ylx_llm_scene_id>

# 智能体平台（必填）
AGENT_PLATFORM_HOST=https://sa-agents-gateway-stg1.paic.com.cn
AGENT_PLATFORM_TOKEN_URL=/appid/auth/login
AGENT_PLATFORM_APP_ID=<your_app_id>
AGENT_PLATFORM_APP_SECRET=<your_app_secret>
AGENT_PLATFORM_KG_ID=<养老险知识库 ID>
AGENT_PLATFORM_RAG_QUERY_URL=/api/open/kn/knSearch
AGENT_PLATFORM_RAG_FAQ_PAGE_URL=/api/open/kn/faq/page
AGENT_PLATFORM_RAG_FAQ_PAGE_SIMILAR_URL=/api/open/kn/faq/pageSimilar
AGENT_PLATFORM_RAG_FAQ_TABLE_LIST_URL=/api/open/kn/tableList
AGENT_PLATFORM_RAG_FAQ_TABLE_DETAIL_URL=/api/open/kn/v2/tableDetailList

# 知识库
KB_MODE=local
SHOUXIAN_AGENT_PLATFORM_KG_ID=<寿险知识库 ID>

# 寿险红利渠道（必填）
ESG_BONUS_CHAT_ADDR=<your_esg_bonus_chat_addr>
ESG_CLIENT_ID_4_BONUS=<xxx>
ESG_CLIENT_SECRET_4_BONUS=<xxx>
ESG_GRANT_TYPE_4_BONUS=client_credentials

# 养老险一键场景（必填）
ESG_OAUTH_URL=<your_esg_oauth_url>
ESG_CLIENT_ID=<xxx>
ESG_CLIENT_SECRET=<xxx>
ESG_GRANT_TYPE=client_credentials
ESG_XIAOAN_CHAT_ADDR=<your_esg_xiaoan_chat_addr>
ESG_TOKEN_EXPIRY=30
XIAOAN_REPOSITORY_ID=<xxx>
```

---

## 维护说明

- **新增 / 删除环境变量必须同步更新本文档和 `.env.sample`**
- 变更"必填"性需要在 PR 描述里说明影响
- 历史遗留无人引用的变量**直接从两边删除**，不再保留"已废弃"清单
- 表格列固定为：`变量名` / `必填` / `默认值` / `示例` / `说明`
- 公司基础设施（监控 agent、日志采集、Ray 框架自身）所需的环境变量不归本文档管理
