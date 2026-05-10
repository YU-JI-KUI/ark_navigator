# API 清单与调用链路

> 本文档由 Kris 在接手项目时整理（2026-05），目标：让接手者一眼看懂每条 API 在做什么、走哪条调用链、谁在调、是否还活着。
>
> 状态约定：
> - 🟢 **活跃**：当前真实在用
> - 🟡 **待确认**：代码存在但调用方不明，需要找上游问清楚后再决定保留还是废弃
> - 🔴 **废弃**：代码或注释已明确标记为不再使用，可清理
> - 🐛 **疑似 bug**：代码看起来有逻辑问题，但按"不改逻辑"原则只记录、不修复

---

## 一、基础路由（系统级）

定义在 [`src/ark_nav/ark_nav_api.py`](../ark_nav_api.py)，由 `APIDeployment` 类暴露。

| 方法 | 路径 | 函数 | 文件:行 | 状态 | 说明 |
|------|------|------|---------|------|------|
| GET | `/` | `root` | ark_nav_api.py:57 | 🟢 | 返回服务名、版本、docs 路径 |
| GET | `/health` | `health` | ark_nav_api.py:65 | 🟢 | 健康检查，固定返回 `{"status": "healthy"}` |
| GET | `/docs` | `custom_swagger_html` | ark_nav_api.py:69 | 🟢 | 自定义 Swagger UI（用了 unpkg CDN，内网部署可能有问题） |

**注**：基础路由用 `@app.get(...)` 装饰，由 `@serve.ingress(app)` 暴露给 Ray Serve。两个 domain 的路由通过 `register_shouxian_routers()` / `register_ylx_routers()` 在初始化时挂载。

---

## 二、寿险（Shouxian）API

定义在 [`src/ark_nav/domains/shouxian/shouxian_api_router.py`](../domains/shouxian/shouxian_api_router.py)，由 `create_shouxian_router(intent_agent_handle, shouxian_nav_agent)` 工厂函数创建，路径前缀 `/api/v1/shouxian`。

### 2.1 `POST /api/v1/shouxian/nav_agent` 🟢 主链路

| 项 | 值 |
|----|----|
| 函数 | `nav_agent` |
| 文件:行 | shouxian_api_router.py:37 |
| 入参 | `ChatCompletionRequest`（router_schemas.py 定义） |
| 调用方 | App 端（前端聊天入口） |
| 是否流式 | ✅ 支持（`request.stream=True` 走 SSE） |

**调用链**：
```
HTTP POST → nav_agent()
  └─ shouxian_nav_agent.process.remote(request)        # Ray Serve 远程调用
     └─ NavAgentDeployment.process()                    # nav_agent.py:41
        └─ ShouXianNavService.run(msg_id, request)      # shouxian_nav_service.py
           ├─ _do_intent_recognition()
           │  └─ IntentClassifyAgentDeployment.classify_intent()
           │     ├─ COTType.NO_COT          → IntentClassifier.classify_user_intent_advance()
           │     │                            ├─ _classify_direct() → call_bigmodel_api()  [simple]
           │     │                            └─ _recognize_with_rewrite() → call_bigmodel_api()
           │     ├─ COTType.COT_MODEL       → IntentCOTClassifier.classify_with_cot_model()
           │     └─ COTType.LLM_WITH_COT_RULES → IntentCOTClassifier.classify_with_cot_rules()
           ├─ fetch_rag()                                # core/services/xiezhi_http.py
           └─ _extract_card_content()
```

**流式实现细节**：
- 用 `asyncio.Queue` + `StreamEventBus` + `create_formatter`（来自 `ark_agentic` 包）
- 流式响应固定输出"收到您的消息，正在处理中..."和"正在调用寿险红利接口...."两条占位文本（shouxian_api_router.py:54-55）

---

### 2.2 `GET /api/v1/shouxian/refresh_prompt` 🟢

| 项 | 值 |
|----|----|
| 函数 | `refresh_root` |
| 文件:行 | shouxian_api_router.py:85 |
| 入参 | 无 |
| 调用方 | 运营后台（手动触发刷新 prompt 缓存） |

**调用链**：
```
HTTP GET → refresh_root()
  └─ init_prompt_from_agent_rag()                      # core/services/xiezhi_http.py
  └─ 返回 {xiezhi: env.XIEZHI_PROMPT, baize: env.BAIZE_PROMPT}
```

**注意**：返回的是**刷新后**的 prompt 内容（直接读环境变量）。说明 `init_prompt_from_agent_rag()` 内部会更新 `os.environ`。

---

### 2.3 `POST /api/v1/shouxian/classify` 🔴 **明确废弃**

| 项 | 值 |
|----|----|
| 函数 | `classify` |
| 文件:行 | shouxian_api_router.py:93 |
| 入参 | `IntentRequest` |
| 调用方 | 画布智能体（已不再使用） |

**代码注释证据**（shouxian_api_router.py:97）：
> `调用方：画布智能体，现在已经不用了，可以删除。`

**额外证据**：
- 装饰器 `@push_to_argilla(...)` 在删除前已被注释掉（shouxian_api_router.py:94）
  - 注：该装饰器及配套的 DataPusherService 已于 2026-05 整体砍除
- 同名 endpoint 在 ylx 侧也存在（ylx_api_router.py:32），含义类似

**调用链**：
```
HTTP POST → classify()
  └─ intent_agent_handle.classify_intent.remote(request)
     └─ IntentClassifyAgentDeployment.classify_intent()
```

**计划**：阶段 2 直接删除。

---

### 2.4 `POST /api/v1/shouxian/search` 🟢

| 项 | 值 |
|----|----|
| 函数 | `search` |
| 文件:行 | shouxian_api_router.py:104 |
| 入参 | `SearchIntentRequest` |
| 调用方 | 业务方（Kris 已确认 2026-05-10） |

**调用链**：
```
HTTP POST → search()
  └─ shouxian_nav_agent.search.remote(request)
     └─ NavAgentDeployment.search()                    # nav_agent.py:55
        └─ ShouXianNavService.search(request)
```

---

### 2.5 `POST /api/v1/shouxian/reset_faiss_index` 🟢

| 项 | 值 |
|----|----|
| 函数 | `reset_faiss_index` |
| 文件:行 | shouxian_api_router.py:112 |
| 入参 | `AgentPfmKbRequest` |
| 调用方 | `scripts/scheduled_knowledge_sync.py`（定时任务） |

**调用链**：
```
HTTP POST → reset_faiss_index()
  └─ broadcast(method_name="reset_faiss_index",
               deployment_name="NavAgentDeployment",   # ← 寿险 deployment
               namespace="serve",
               app_name="default",
               request=request)
     └─ 调用所有 NavAgentDeployment 副本的 reset_faiss_index() 方法
        └─ AgentPfmKbService.load_data(kg_id, is_reload)  # 重新加载 FAISS 索引
```

**实现说明**：用 `broadcast` 工具（core/utils/broadcast_utils.py）向**所有副本**广播执行，确保多副本场景下索引一致。

---

## 三、养老险（YLX）API

定义在 [`src/ark_nav/domains/yanglaoxian/ylx_api_router.py`](../domains/yanglaoxian/ylx_api_router.py)，由 `create_router(agent_handler)` 工厂函数创建，路径前缀 `/api/v1/ylx`。

### 3.1 `GET /api/v1/ylx/refresh` 🟢

| 项 | 值 |
|----|----|
| 函数 | `refresh` |
| 文件:行 | ylx_api_router.py:25 |
| 入参 | 无 |
| 调用方 | 运营后台 |

**调用链**：
```
HTTP GET → refresh()
  └─ init_prompt_from_agent_rag()                      # 与寿险共用同一函数
  └─ 返回 {ylx: env.YLX_PROMPT}
```

**与寿险差异**：
- 寿险路径是 `/refresh_prompt`，养老险是 `/refresh` —— 命名不一致
- 调用同一个 `init_prompt_from_agent_rag()`，但只返回 `YLX_PROMPT`

---

### 3.2 `POST /api/v1/ylx/classify` 🔴 **明确废弃**

| 项 | 值 |
|----|----|
| 函数 | `classify` |
| 文件:行 | ylx_api_router.py:32 |
| 入参 | `IntentRequest`（注意：复用了寿险的 schema） |
| 调用方 | 无（Kris 已确认不需要 2026-05-10） |

**调用链**：
```
HTTP POST → classify()
  └─ agent_handler.process.remote(request.user_message, request.history)
     └─ NavYLXAgentDeployment.process(query, msg_id)   # ylx_nav_agent.py:62
```

**🐛 疑似 bug 1**：参数错位
- 此处调用 `process.remote(request.user_message, request.history)`，传入两个位置参数
- 但 `NavYLXAgentDeployment.process()` 签名是 `(query: str, msg_id: str = None)`
- **`request.history` 会被当成 `msg_id` 传进去**
- 如果 history 是 list 类型，`process` 内部 `logger.info(f"{msg_id}, ...")` 会打出整个 history 列表当作 msg_id —— 不会立刻报错，但日志会很怪
- **行动**：阶段 2 不修，记录在此

**与寿险 `/classify` 对比**：
- 寿险版已被代码注释标记为废弃
- 养老险版**没有标记**，但调用方也未知 —— Kris 需要进一步确认

**装饰器**：原 `@push_to_argilla(...)` 在 ylx 侧仍激活（ylx_api_router.py:33），与寿险版被注释相反。
该装饰器及配套的 DataPusherService 已于 2026-05 整体砍除。

---

### 3.3 `POST /api/v1/ylx/navi` 🟢 主链路

| 项 | 值 |
|----|----|
| 函数 | `navi` |
| 文件:行 | ylx_api_router.py:42 |
| 入参 | `YLXRequest` |
| 调用方 | App 端 |
| 是否流式 | ✅ 支持 |

**调用链**：
```
HTTP POST → navi()
  └─ agent_handler.run.remote(request)
     └─ NavYLXAgentDeployment.run()                    # ylx_nav_agent.py:119
        ├─ self.process(query, msg_id)                 # 内部意图识别
        │  ├─ enable_local_kg=true → AgentPfmKbService.search()
        │  └─ enable_local_kg=false → fetch_rag()
        │  └─ 都没命中 → call_bigmodel_api()           # 走 LLM 兜底
        └─ intent.result == "养老险意图":
           └─ OneKeyService.process()                  # onekey_service.py
              └─ 返回 YLXResponse(card_content, ...)
```

**遗留代码痕迹**：
- 流式分支里写死的中文是"**正在调用寿险红利接口...**"（ylx_api_router.py:62），明显是从寿险 router 拷贝过来未改
- `formatter` 的 `source_bu_type="shouxian"`、`app_type="jgj"`（ylx_api_router.py:55-56）—— 同样是拷贝寿险的痕迹
- **不改逻辑红线**：先记录，不动

---

### 3.4 `POST /api/v1/ylx/reset_faiss_index` 🟢 但有 bug

| 项 | 值 |
|----|----|
| 函数 | `reset_faiss_index` |
| 文件:行 | ylx_api_router.py:92 |
| 入参 | `AgentPfmKbRequest` |
| 调用方 | `scripts/scheduled_knowledge_sync.py`（定时任务） |

**🐛 疑似 bug 2**：广播到了错误的 deployment
```python
# ylx_api_router.py:96-102
broadcast(
    method_name="reset_faiss_index",
    deployment_name="NavAgentDeployment",   # ← 应为 NavYLXAgentDeployment
    namespace="serve",
    app_name="default",
    request=request
)
```
- 这个端点名义上是"重置养老险的 FAISS 索引"
- 但 `deployment_name` 写的是 `NavAgentDeployment`（寿险的）
- 结果：**调用 `/api/v1/ylx/reset_faiss_index` 实际重置的是寿险的 FAISS 索引**
- 寿险和养老险用的 `kg_id` 不同，所以这个 bug 可能导致养老险的索引从未被这个接口刷新过

**对比**：寿险 `reset_faiss_index` 写的也是 `NavAgentDeployment`，对寿险来说是正确的。所以养老险这里 99% 是直接拷贝寿险代码漏改了。

**行动**：
- 阶段 2 不修
- Kris 应该尽快和业务/运维确认：养老险的 FAISS 是怎么刷新的？是否有别的途径？还是说一直都没正常刷新过？
- 这是后续单独建 issue 修复的事项，不在本次"结构整改"范围

---

## 四、调用链聚合视图

```
                                 ┌────────────────────────────────┐
                                 │       APIDeployment            │
                                 │   (FastAPI + Ray serve.ingress) │
                                 └───────────────┬────────────────┘
                                                 │
                ┌────────────────────────────────┼─────────────────────────────────┐
                │                                │                                  │
        ┌───────▼─────────┐              ┌──────▼─────────┐                ┌──────▼──────┐
        │  shouxian/*     │              │   ylx/*        │                │  /, /health │
        │  router         │              │  router        │                │  /docs      │
        └───┬─────┬───┬───┘              └──┬──┬───┬──┬───┘                └─────────────┘
            │     │   │                     │  │   │  │
            │     │   │                     │  │   │  │
   ┌────────▼┐  ┌─▼─┐ │                  ┌──▼┐ │ ┌─▼┐ │
   │nav_agent│  │…  │ │                  │navi│ │ │…│ │
   └────┬────┘  └───┘ │                  └─┬──┘ │ └──┘ │
        │             │                    │    │      │
        │  ┌──────────▼─┐                  │    │      │
        │  │/refresh_   │                  │    │      │
        │  │ prompt     │                  │    │      │
        │  └────────────┘                  │    │      │
        │                                  │    │      │
        │       ┌──────reset_faiss─────────┼────┘      │
        │       │ (寿险:✅ 养老险:🐛)        │           │
        │       │                          │           │
        ▼       ▼                          ▼           ▼
┌───────────────────┐            ┌───────────────────────┐
│ NavAgentDeployment│            │ NavYLXAgentDeployment │
│   .process()      │            │   .process() / .run() │
│   .search()       │            │   .reset_faiss_index()│
│   .reset_…()      │            │                       │
└────┬──────────┬───┘            └───┬───────────────────┘
     │          │                    │
     ▼          ▼                    ▼
┌──────────┐ ┌──────────────┐  ┌─────────────────┐
│ShouXian  │ │AgentPfmKb    │  │ OneKeyService   │
│NavService│ │Service       │  │ XiaoAnRobot     │
└──────────┘ └──────────────┘  └─────────────────┘
     │
     ▼
┌──────────────────────────┐
│IntentClassifyAgentDeploy.│
│  ├ IntentClassifier      │
│  ├ IntentCOTClassifier   │
│  └ ShouxianBertDeploy.   │
└──────────────────────────┘
```

---

## 五、状态汇总表

| 路径 | 状态 | 阶段 2 动作 |
|------|------|-------------|
| `GET /` | 🟢 | 保留 |
| `GET /health` | 🟢 | 保留 |
| `GET /docs` | 🟢 | 保留（但 unpkg CDN 内网可能挂，单独 issue） |
| `POST /api/v1/shouxian/nav_agent` | 🟢 | 保留 |
| `GET /api/v1/shouxian/refresh_prompt` | 🟢 | 保留 |
| `POST /api/v1/shouxian/classify` | 🔴 | **删除** |
| `POST /api/v1/shouxian/search` | 🟢 | 保留 |
| `POST /api/v1/shouxian/reset_faiss_index` | 🟢 | 保留 |
| `GET /api/v1/ylx/refresh` | 🟢 | 保留 |
| `POST /api/v1/ylx/classify` | 🔴 | **删除** |
| `POST /api/v1/ylx/navi` | 🟢 | 保留 |
| `POST /api/v1/ylx/reset_faiss_index` | 🟢🐛 | 保留 + TODO 标记 deployment_name bug |

---

## 六、本次整改不修但需要后续单独跟进的 bug 列表

> 这些都是结构整改过程中**只读出来、不修复**的发现。Kris 应该把它们单独建 issue/工单，按业务优先级排期。

| ID | 位置 | 描述 | 严重度 |
|----|------|------|--------|
| BUG-1 | ylx_api_router.py:98 | `reset_faiss_index` 的 `deployment_name` 写错为 `NavAgentDeployment`，应为 `NavYLXAgentDeployment` | 高 |
| BUG-2 | ylx_api_router.py:39 | `classify` 端点把 `request.history` 当 `msg_id` 传给 `process()`，参数错位 | 中 |
| BUG-3 | ylx_api_router.py:55-56, 62 | navi 流式分支拷贝了寿险的 `source_bu_type="shouxian"` 和"寿险红利"文案 | 低（用户体验） |
| BUG-4 | shouxian/intent_classifier_simple.py:64 | 注释写"默认返回拒识"，但实际返回 `"寿险意图"` | 中 |
| BUG-5 | shouxian/intent_classifier_advance.py:144,148 | 异常分支返回 `IntentResult("error", ...)`，但上游代码只识别 `"寿险意图"` 和 `"拒识"` | 低 |
