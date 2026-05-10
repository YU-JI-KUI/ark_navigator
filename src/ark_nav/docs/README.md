# Ark Navigator 接手文档

本目录是 Kris 在接手项目时整理的"地图"，目的是让接手者（包括未来的自己）能快速理解项目结构、API 边界、配置依赖。

## 文档索引

| 文档 | 用途 | 主要回答 |
|------|------|---------|
| [API_INVENTORY.md](API_INVENTORY.md) | API 清单与调用链路 | 有哪些 API？谁在调？是不是死的？调用链怎么走？ |
| [ENV_INVENTORY.md](ENV_INVENTORY.md) | 环境变量清单 | 哪些变量真在用？哪些是死配置？哪些是隐藏的？敏感的有哪些？ |
| [MODULE_MAP.md](MODULE_MAP.md) | 模块依赖图 | 项目目录怎么分层？Deployment 拓扑？xiezhi_http.py 怎么拆？ |

## 整改背景

这些文档是 2026-05 月接手项目整改的"阶段 1 输出"。核心约束：

- ✅ **可以改结构**（拆文件、合并重复、清理死代码、统一日志/配置）
- ❌ **不能改逻辑**（任何 if/else、return 值、外部调用顺序、参数都不动）

整改完整方案见 [`~/.claude/plans/ai-python-rosy-wigderson.md`](file:///Users/kris/.claude/plans/ai-python-rosy-wigderson.md)（个人计划文件，不在仓库内）。

## 已发现但本次整改不修的 bug 清单

为了守住"不改逻辑"的红线，整改过程中发现的 bug 全部记录在这里、单独建 issue 修。

| ID | 文档 | 描述 | 严重度 |
|----|------|------|--------|
| BUG-1 | [API#3.4](API_INVENTORY.md) | ylx 的 `reset_faiss_index` 把 broadcast 发给了 `NavAgentDeployment`（应为 `NavYLXAgentDeployment`） | 高 |
| BUG-2 | [API#3.2](API_INVENTORY.md) | ylx 的 `classify` 端点把 `request.history` 当 `msg_id` 传给 `process()`，参数错位 | 中 |
| BUG-3 | [API#3.3](API_INVENTORY.md) | ylx `navi` 流式分支沿用了寿险的 `source_bu_type="shouxian"` 和"寿险红利"中文 | 低 |
| BUG-4 | [API#六](API_INVENTORY.md) | `intent_classifier_simple.py:64` 注释写"默认返回拒识"但实际 `return "寿险意图"` | 中 |
| BUG-5 | [API#六](API_INVENTORY.md) | `intent_classifier_advance.py:144,148` 异常分支返回 `IntentResult("error", ...)`，上游不识别 | 低 |
| BUG-6 | [ENV#4.2](ENV_INVENTORY.md) | `scheduled_knowledge_sync.py:23` 中 `int(os.getenv("RAG_EXECUTION_TIMEOUT"), 600)` 把 600 当 base，运行时直接抛 TypeError | 高 |
| BUG-7 | [ENV#八](ENV_INVENTORY.md) | `agent_platform_config.py:9-10` 变量名 `TENANT_ID`/`APP_SEC` 与环境变量名错位 | 低 |
| BUG-8 | [ENV#八](ENV_INVENTORY.md) | 寿险/养老险 KG_ID 命名不对称 (`SHOUXIAN_AGENT_PLATFORM_KG_ID` vs `AGENT_PLATFORM_KG_ID`) | 中 |

> Kris：把这些一条条建成正式 issue，按业务优先级排期修复（不在本次结构整改范围）。
