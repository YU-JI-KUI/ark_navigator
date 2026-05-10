# 环境变量清单

> 本文档由 Kris 在接手项目时整理（2026-05），基于对 `src/` 和 `scripts/` 全量 grep `os.getenv` / `os.environ` 的结果，结合 `.env.sample` 与 `Settings`（pydantic-settings）逐项核对。
>
> 状态约定：
> - **A 类**（活）：`.env.sample` 中声明 + 代码中真实读取 → 保留
> - **B 类**（死）：`.env.sample` 中声明 + 代码中**完全没有读取** → 阶段 3 清理
> - **C 类**（隐）：代码中读取 + `.env.sample` 中**未声明** → 阶段 3 补声明
> - **D 类**（疑）：变量名相似/语义重叠/读取方式分裂 → 阶段 3 文档化，不合并

---

## 一、配置加载机制现状（3 套并存）

| 机制 | 文件 | 管的变量 | 备注 |
|------|------|---------|------|
| **Pydantic Settings** | [`src/ark_nav/config.py`](../config.py) | 模型路径、批处理、端口、日志级别等 9 个 | 本质上和 .env 解耦，从 `Settings()` 实例读，**目前未广泛使用** |
| **自定义 Config 类（LLMPlfConfig）** | [`src/ark_nav/core/utils/llm_platform_config.py`](../core/utils/llm_platform_config.py) | LLM 平台 API（`OPEN_AI_URL`、`RSA_PK`、`CRE_ID`、`OPEN_API_CODE`、`YLX_LLM_*`）共 7 个 | 类属性在导入时一次性 `os.getenv`，运行时不动态刷新 |
| **自定义 Config 类（AgentPfmConfig）** | [`src/ark_nav/core/utils/agent_platform_config.py`](../core/utils/agent_platform_config.py) | 智能体平台 API（`AGENT_PLATFORM_*`）共 10 个 | 同上 |
| **散点 `os.getenv()`** | 全项目 50+ 处 | 其余所有变量 | 业务代码直接读，无统一管理 |

**结论**：第一轮整改 **不动配置加载机制**（动了等于改逻辑）。仅做"事实层面"的清理：删死配置、补隐藏配置、文档化重复。

---

## 二、A 类：声明 + 在用（保留）

总数 **41 个**（原 42 个；2026-05 砍除 DataPusherService 后 `DATAPULSE_URL` 移至底部"已删除"区）。按业务分组：

### 2.1 应用基础（3 个）

| 变量 | .env.sample 默认值 | 代码引用 | 真实作用 |
|------|------------------|---------|---------|
| `APP_HOST` | `0.0.0.0` | ❌ 无引用 | 见 B 类 |
| `APP_PORT` | `8080` | 通过 `Settings.port` 间接关联 | 但 `Settings.port` 用的是默认值 `8080`，不读 `APP_PORT` |
| `ENVIRONMENT` | `development` | ❌ 无引用 | 见 B 类 |

> ⚠️ 注：这一组**全部进 B 类**。下面其他分组才是真正"在用"的。

### 2.2 平安大模型 API（7 个，主链路核心）

| 变量 | 引用位置 | 含义 |
|------|---------|------|
| `RSA_PK` | LLMPlfConfig.RSA_PK (llm_platform_config.py:7) | 🔐 RSA 私钥（用于 open_ai_signature） |
| `APP_KEY` | intent_classifier_simple.py:77; shouxian_nav_service.py:516 | 🔐 寿险大模型 app_key |
| `APP_SECRET` | intent_classifier_simple.py:78; shouxian_nav_service.py:517 | 🔐 寿险大模型 app_secret |
| `CRE_ID` | LLMPlfConfig.CRE_ID (llm_platform_config.py:8) | 🔐 凭证 ID |
| `OPEN_API_CODE` | LLMPlfConfig.OPEN_API_CODE (llm_platform_config.py:9) | 🔐 开放接口编码 |
| `SCENE_ID` | intent_classifier_simple.py:34 | 寿险意图识别场景 ID |
| `OPEN_AI_URL` | LLMPlfConfig.OPEN_AI_URL (llm_platform_config.py:6) | LLM 网关地址 |

### 2.3 意图重写模型（3 个）

| 变量 | 引用位置 |
|------|---------|
| `INTENT_REWRITE_SCENE_ID` | intent_classifier_advance.py:168, intent_classifier_cot.py:71,117, onekey_service.py:146 |
| `INTENT_REWRITE_APP_KEY` | 同上多处 |
| `INTENT_REWRITE_APP_SECRET` | 同上多处 |

### 2.4 养老险大模型（3 个）

| 变量 | 引用位置 |
|------|---------|
| `YLX_LLM_SCENE_ID` | LLMPlfConfig.YLX_LLM_SCENE_ID (llm_platform_config.py:13) |
| `YLX_LLM_APP_KEY` | LLMPlfConfig.YLX_LLM_APP_KEY (llm_platform_config.py:11) |
| `YLX_LLM_APP_SECRET` | LLMPlfConfig.YLX_LLM_APP_SECRET (llm_platform_config.py:12) |

### 2.5 智能体平台（10 个，AgentPfmConfig 全集）

| 变量 | 在 AgentPfmConfig 中的属性名 |
|------|-------------------------|
| `AGENT_PLATFORM_HOST` | `HOST` |
| `AGENT_PLATFORM_TOKEN_URL` | `TOKEN_URL` |
| `AGENT_PLATFORM_RAG_QUERY_URL` | `RAG_QUERY_URL` |
| `AGENT_PLATFORM_KG_ID` | `KG_ID`（**养老险**用，见 D 类） |
| `AGENT_PLATFORM_APP_ID` | `TENANT_ID` ⚠️ 名字错位 |
| `AGENT_PLATFORM_APP_SECRET` | `APP_SEC` ⚠️ 缩写不一致 |
| `AGENT_PLATFORM_RAG_FAQ_PAGE_URL` | `RAG_FAQ_PAGE_URL` |
| `AGENT_PLATFORM_RAG_FAQ_PAGE_SIMILAR_URL` | `RAG_FAQ_PAGE_SIMILAR_URL` |
| `AGENT_PLATFORM_RAG_FAQ_TABLE_LIST_URL` | `RAG_FAQ_TABLE_LIST_URL` |
| `AGENT_PLATFORM_RAG_FAQ_TABLE_DETAIL_URL` | `RAG_FAQ_TABLE_DETAIL_URL` |

**⚠️ 命名混乱**：
- `AGENT_PLATFORM_APP_ID` → 内部叫 `TENANT_ID`（语义都对，但读起来要在两个名字之间换算）
- `AGENT_PLATFORM_APP_SECRET` → 内部叫 `APP_SEC`（缩写残缺，容易误解）
- 这些是"改名属于改逻辑"的红线区，**第一轮不改**，仅文档化。

### 2.6 寿险知识库（1 个）

| 变量 | 引用位置 |
|------|---------|
| `SHOUXIAN_AGENT_PLATFORM_KG_ID` | nav_agent.py:38; shouxian_nav_service.py:488; scripts/scheduled_knowledge_sync.py:41 |

### 2.7 体验评估模型（3 个，仅 CoT 用到）

| 变量 | 引用位置 |
|------|---------|
| `EXP_APP_KEY` | intent_classifier_cot.py:166 |
| `EXP_APP_SECRET` | intent_classifier_cot.py:167 |
| `EXP_SCENE_ID` | intent_classifier_cot.py:168 |

### 2.8 ESG 小安机器人（YLX 用，6 个）

| 变量 | 引用位置 |
|------|---------|
| `ESG_OAUTH_URL` | onekey_service.py:93 |
| `ESG_CLIENT_ID` | onekey_service.py:94 |
| `ESG_GRANT_TYPE` | onekey_service.py:95 |
| `ESG_CLIENT_SECRET` | onekey_service.py:96 |
| `ESG_TOKEN_EXPIRY` | onekey_service.py:109; shouxian_nav_service.py:387 |
| `ESG_XIAOAN_CHAT_ADDR` | onekey_service.py:86 |

### 2.9 ESG Bonus（寿险红利专用，5 个）

| 变量 | 引用位置 |
|------|---------|
| `ESG_OAUTH_URL` | shouxian_nav_service.py:371（**与 2.8 共用同一变量**） |
| `ESG_CLIENT_ID_4_BONUS` | shouxian_nav_service.py:372 |
| `ESG_GRANT_TYPE_4_BONUS` | shouxian_nav_service.py:373 |
| `ESG_CLIENT_SECRET_4_BONUS` | shouxian_nav_service.py:374 |
| `ESG_BONUS_CHAT_ADDR` | shouxian_nav_service.py:364 |
| ~~`ESG_TOKEN_EXPIRY_4_BONUS`~~ | ❌ **未引用**（见 B 类） |

### 2.10 ~~数据推送~~（已删除）

> 该章节原本声明 `DATAPULSE_URL`，对应 `data_pusher_service.py` 中的 `DataPusherService` 类。
> 该功能在 2026-05 已整体砍除（见底部"已删除的配置"区块）。

### 2.11 RAG / FAISS / 本地知识库（2 个）

| 变量 | 引用位置 |
|------|---------|
| `FAISS_INDEX_DIR` | agent_pfm_kb_service.py:22 |
| `ENABLE_LOCAL_KG` | agent_pfm_kb_service.py:24; shouxian_nav_service.py:479; ylx_nav_agent.py:67; onekey_service.py:40,153 |

### 2.12 Ray Serve（2 个）

| 变量 | 引用位置 |
|------|---------|
| `RAY_MIN_REPLICAS` | ark_nav_api.py:11; nav_agent.py:16; intent_classify_agent.py:12; bert.py:10; rag_models.py:9 |
| `RAY_INITIAL_REPLICAS` | nav_agent.py:17; intent_classify_agent.py:13 |

### 2.13 定时任务（1 个）

| 变量 | 引用位置 |
|------|---------|
| `RAG_EXECUTION_TIME` | scripts/scheduled_knowledge_sync.py:52（执行时刻，如 `21:30`） |

---

## 三、B 类：声明了但代码完全不读（**死配置，阶段 3 删除**）

| 变量 | .env.sample 行 | 死亡证据 |
|------|---------------|---------|
| `APP_HOST` | :4 | grep 全项目无 `APP_HOST` 引用 |
| `APP_PORT` | :5 | grep 全项目无 `APP_PORT` 引用（端口 8080 是 `Settings.port` 默认值） |
| `ENVIRONMENT` | :6 | grep 全项目无 `ENVIRONMENT` 引用 |
| `NEW_RELIC_CONFIG_FILE` | :51 | grep 全项目无引用 |
| `DETECTOR_AGENT_ID` | :52 | grep 全项目无引用 |
| `DETECTOR_COLLECTOR_IP` | :53 | grep 全项目无引用 |
| `caas_logs_app` | :58 | grep 全项目无引用 |
| `AGENT_PLATFORM_KG_ID_YLX` | :101 | grep 全项目无引用（养老险实际用的是 `AGENT_PLATFORM_KG_ID`，见 D 类） |
| `ESG_TOKEN_EXPIRY_4_BONUS` | :90 | grep 全项目无引用（红利路径复用了 `ESG_TOKEN_EXPIRY`） |

**总计 9 个死配置。** 阶段 3 直接从 `.env.sample` 删除，并把删除原因写到该文件的注释里（防后人再加回来）。

---

## 四、C 类：代码在读但 .env.sample 没声明（**隐藏配置，阶段 3 补声明**）

| 变量 | 引用位置 | 真实来源 / 含义 |
|------|---------|----------------|
| `XIEZHI_PROMPT` | shouxian_api_router.py:89; intent_classifier_simple.py:35 | 由 `init_prompt_from_agent_rag()` 在运行时从智能体平台拉取，**写入 `os.environ`**（xiezhi_http.py:114） |
| `BAIZE_PROMPT` | shouxian_api_router.py:90; intent_classifier_advance.py:171 | 同上，xiezhi_http.py:117 |
| `YLX_PROMPT` | ylx_api_router.py:29; ylx_nav_agent.py:55 | 同上，xiezhi_http.py:120 |
| `XIAOAN_REPOSITORY_ID` | onekey_service.py:199 | 小安机器人知识库 ID（int 类型） |
| `RAG_EXECUTION_TIMEOUT` | scripts/scheduled_knowledge_sync.py:23 | HTTP 超时（秒）。**注意**：与 `RAG_EXECUTION_TIME`（执行时刻）是两个不同的东西！ |

**5 个隐藏配置。**

### 4.1 关于 `XIEZHI_PROMPT` / `BAIZE_PROMPT` / `YLX_PROMPT` 的特殊性

这三个 prompt 变量**理论上不该出现在 `.env.sample`**，因为它们是程序运行时从智能体平台动态拉取的（见 `xiezhi_http.py:104-121`），不是部署时配置的。

**但**：如果智能体平台不可达 / `init_prompt_from_agent_rag()` 没被调用，代码就会读到 `None`，下游可能崩。

**阶段 3 处理建议**：
- 在 `.env.sample` 里**加注释说明**，但不需要给默认值
- 或者写一个特殊章节："# 这些变量由 init_prompt_from_agent_rag() 在运行时从智能体平台拉取后写入 os.environ，不需要手动配置"

### 4.2 关于 `RAG_EXECUTION_TIMEOUT`（含 bug）

🐛 **疑似 bug 6**：[scripts/scheduled_knowledge_sync.py:23](../../scripts/scheduled_knowledge_sync.py#L23)
```python
timeout=int(os.getenv("RAG_EXECUTION_TIMEOUT"), 600)
```
- 这里 `int(x, 600)` 把 600 当成**进制 base**（`int` 的第二个参数语义），不是默认值
- 当 `RAG_EXECUTION_TIMEOUT` 未配置时，`os.getenv` 返回 `None`，`int(None, 600)` 直接抛 `TypeError`
- 正确写法应是 `int(os.getenv("RAG_EXECUTION_TIMEOUT", "600"))`
- **不改逻辑红线**：阶段 1-5 不修，阶段 6 之后单独 issue 修

---

## 五、D 类：变量名相似/语义重叠（**文档化，不合并**）

### 5.1 寿险/养老险 KG_ID 命名分裂

| 变量 | 用在哪 | 含义 |
|------|-------|------|
| `SHOUXIAN_AGENT_PLATFORM_KG_ID` | nav_agent.py:38 (寿险 NavAgent), shouxian_nav_service.py:488, scripts/scheduled_knowledge_sync.py:41 | **寿险**知识库 ID |
| `AGENT_PLATFORM_KG_ID` | AgentPfmConfig.KG_ID, ylx_nav_agent.py:58 (**养老险** NavAgent), scripts/scheduled_knowledge_sync.py:44 | **养老险**知识库 ID |

**问题**：
- 寿险变量带 `SHOUXIAN_` 前缀，养老险变量没有 `YLX_` 前缀，**语义不对称**
- 看变量名 `AGENT_PLATFORM_KG_ID`（无业务前缀），不读代码根本猜不到它是养老险专用
- `.env.sample` 里另有 `AGENT_PLATFORM_KG_ID_YLX`（B 类死配置），曾经可能想统一用这个名字但没改完

**第一轮整改不改名（属于改逻辑/部署侧）**，仅在 ENV_INVENTORY.md 高亮风险。

### 5.2 ESG 双套配置（OAuth/Token 两套并存）

| 用途 | 变量集 |
|------|-------|
| **YLX 小安机器人**（onekey_service.py） | `ESG_CLIENT_ID`, `ESG_GRANT_TYPE`, `ESG_CLIENT_SECRET`, `ESG_TOKEN_EXPIRY`, `ESG_XIAOAN_CHAT_ADDR`, `ESG_OAUTH_URL` |
| **寿险红利渠道**（shouxian_nav_service.py） | `ESG_CLIENT_ID_4_BONUS`, `ESG_GRANT_TYPE_4_BONUS`, `ESG_CLIENT_SECRET_4_BONUS`, `ESG_TOKEN_EXPIRY`（共用！）, `ESG_BONUS_CHAT_ADDR`, `ESG_OAUTH_URL`（共用！） |

**说明**：这是**有意为之**的两套渠道（养老险 vs 寿险红利），不是 bug。但：
- `ESG_TOKEN_EXPIRY` 两边共用 —— 暗示两个渠道的 token 有效期一定相同，未来如果业务想分开会很尴尬
- `ESG_TOKEN_EXPIRY_4_BONUS` 在 .env.sample 里有定义但代码不读（B 类死配置）—— 说明本来想分开但漏写了

**仅文档化，第一轮不动。**

### 5.3 容易与 RAG_EXECUTION_TIME 混淆

| 变量 | 含义 |
|------|-----|
| `RAG_EXECUTION_TIME` (A 类) | 定时任务**触发时刻**，如 `21:30` |
| `RAG_EXECUTION_TIMEOUT` (C 类) | HTTP 调用**超时秒数**（被 bug 掩盖） |

变量名只差 `OUT` 三个字母，语义完全不同。**保留两者**，但在 .env.sample 里要写清楚区别。

---

## 六、敏感变量清单（运维交接必看）

下列变量含密钥/凭证类内容，部署侧需要从生产配置同步，**不要把真实值提交到代码仓库**：

```
🔐 RSA_PK
🔐 APP_KEY / APP_SECRET
🔐 CRE_ID / OPEN_API_CODE
🔐 INTENT_REWRITE_APP_KEY / INTENT_REWRITE_APP_SECRET
🔐 YLX_LLM_APP_KEY / YLX_LLM_APP_SECRET
🔐 EXP_APP_KEY / EXP_APP_SECRET
🔐 AGENT_PLATFORM_APP_SECRET
🔐 ESG_CLIENT_ID / ESG_CLIENT_SECRET
🔐 ESG_CLIENT_ID_4_BONUS / ESG_CLIENT_SECRET_4_BONUS
```

**共 14 个敏感变量**，阶段 3 重写 `.env.sample` 时全部用 `🔐` 标记。

---

## 七、变量数量汇总

| 分类 | 数量 | 阶段 3 动作 |
|------|------|-----------|
| A 类（活，保留） | 41 | 重写 sample 时分组、加注释（原 42，砍除 DATAPULSE_URL 后剩 41） |
| B 类（死，删除） | 9 | 从 sample 删除 + 注释说明删除原因 |
| C 类（隐，补声明） | 5 | 加到 sample（prompt 类加特殊章节） |
| D 类（疑，文档化） | 3 组 | 仅在 sample 加 ⚠️ 注释 |
| 功能砍除（DataPusherService） | 1 | 砍除 DATAPULSE_URL（2026-05） |
| **sample 现共 50 个** → **第一轮整改后 46 个** → **DataPusherService 砍除后 45 个** | | |

---

## 八、本次整改不修但需要后续单独跟进的 bug 列表（环境变量相关）

| ID | 位置 | 描述 | 严重度 |
|----|------|------|--------|
| BUG-6 | scripts/scheduled_knowledge_sync.py:23 | `int(os.getenv("RAG_EXECUTION_TIMEOUT"), 600)` 把 600 当 base 而非默认值，且变量未声明，运行时直接抛 TypeError | 高 |
| BUG-7 | core/utils/agent_platform_config.py:9-10 | `AGENT_PLATFORM_APP_ID` 映射到 `TENANT_ID`、`AGENT_PLATFORM_APP_SECRET` 映射到 `APP_SEC`（不完整缩写） | 低（命名规范） |
| BUG-8 | .env.sample vs 代码 | 寿险/养老险 KG_ID 命名不对称（`SHOUXIAN_AGENT_PLATFORM_KG_ID` vs `AGENT_PLATFORM_KG_ID`） | 中（可读性） |

> Bug 编号承接 [API_INVENTORY.md](API_INVENTORY.md) 的 BUG-1 ~ BUG-5。
