# 日志规范

> 本文档由 Kris 在接手项目时整理（2026-05），用于阶段 4"日志规范统一"整改的执行依据。
>
> 整改原则：**只改"打印方式"，不改"日志内容"**。
> - ✅ 改：`print()` → `logger.xxx`、`traceback.print_exc()` → `exc_info=True`、`logging.getLogger()` → `get_logger()`
> - ❌ 不改：日志消息文本、日志级别、不删任何日志（即使看起来无用）

---

## 一、统一约定

### 1.1 唯一允许的 logger 来源

```python
from ark_nav.core.utils.nav_logger import get_logger

logger = get_logger(__name__)
```

**禁止**：
- ❌ `print(...)` —— 完全绕过日志系统
- ❌ `import logging; logger = logging.getLogger(__name__)` —— 失去 trace_id 注入
- ❌ `traceback.print_exc()` —— 不带级别、不带 logger 名、不进 trace_id 链路

### 1.2 错误日志规范

```python
# ❌ 旧写法（异常栈丢失或散落）
try:
    ...
except Exception as e:
    traceback.print_exc()
    logger.error(f"调用失败: {str(e)}")

# ✅ 新写法（一行带栈）
try:
    ...
except Exception as e:
    logger.error(f"调用失败: {str(e)}", exc_info=True)
```

> 关键：`exc_info=True` 让 structlog 把完整异常栈拼到日志里，等价于原来的 `traceback.print_exc()` + `logger.error(str(e))` 二合一。

### 1.3 trace_id 自动注入（已存在的能力）

`nav_logger.py` 里 `_add_trace_id_processor` 已经实现：**任何通过 `get_logger()` 返回的 logger，打日志时会自动从 ContextVar 读 trace_id 并注入**。

只要满足以下两点，trace_id 会贯穿整个请求链路：
1. 请求入口设置过 `set_trace_id(...)` —— `TraceIDMiddleware` 已做
2. 下游所有日志走 `get_logger()` 返回的 logger

**当前问题**：`trace_id_middleware.py` 自己用 `print(...)` 打日志，导致中间件这一段 trace_id 没法注入。阶段 4.2 修复。

---

## 二、机械替换规则（阶段 4 严格遵守）

### 2.1 替换矩阵

| 旧写法 | 新写法 | 备注 |
|--------|--------|------|
| `print(f"启动 xxx")` | `logger.info("启动 xxx")` | 信息打印 → INFO |
| `print(f"[INFO] xxx")` | `logger.info("xxx")` | 去掉冗余级别前缀 |
| `print(f"[ERROR] xxx")` | `logger.error("xxx")` | 同上 |
| `print(f"❌ xxx: {e}")` | `logger.error(f"xxx: {e}", exc_info=True)` | 异常类 print 改 error+栈 |
| `print(f"=" * 60)` 这种装饰线 | `logger.info("=" * 60)` 或合并到下一条 | **保留**，不删 |
| `traceback.print_exc()` 单独一行 | 删除该行 + 在配套的 `logger.error` 上加 `exc_info=True` | 二合一 |
| `import traceback` 后无其他用法 | 删除该 import | 连带清理 |
| `logging.getLogger(__name__)` | `get_logger(__name__)` | 切到 structlog |
| `logging.error(...)` 模块级调用 | `get_logger(__name__).error(...)` | 同上 |

### 2.2 严格红线（**违反 = 改逻辑**）

| 行为 | 是否允许 |
|------|---------|
| 改日志消息中文/英文文本 | ❌ |
| 改日志格式（如把 `x = {y}` 改成 `x={y}`） | ❌ |
| 改日志级别（`info` ↔ `debug` 等） | ❌ 阶段 4 不改，留到第二轮 |
| **删除任何**已有日志（即使看起来无用） | ❌ |
| **新增**日志（即使能补全关键节点） | ❌ 阶段 4 不加，留到后期 |
| 给现有 `logger.error(f"x: {e}")` 加 `exc_info=True` | ✅ 仅当配套有 `traceback.print_exc()` 才加 |
| 删 `import traceback`（如该文件已不再用） | ✅ |
| 删 `import logging`（如改用 `get_logger` 后已不再用） | ✅ |

### 2.3 特殊情况：含 emoji 的 print

`serve_app.py` 里有 `print(f"\U0001f680 服务已启动")` 这种带 emoji 的启动 banner。

**处理**：保留 emoji 不变，只把 `print(...)` 改成 `logger.info(...)`。emoji 是 unicode 字符，不影响 structlog 渲染。

### 2.4 特殊情况：装饰器内的 print

`nav_logger.py:170, 174, 183, 187` 的 `print_execution_time` 装饰器自身用 `print(f"[INFO] xxx")`。

**处理**：装饰器内部要先 `import` 自己的 `get_logger`：
```python
# nav_logger.py 里加：
_decorator_logger = structlog.get_logger("ark_nav.exec_time")
```

然后把 `print(...)` 改成 `_decorator_logger.info(...)` / `.error(...)`。**不要**在装饰器里再调一次 `get_logger("xxx")`，那样每次调用都会走 structlog 缓存查找，性能差。

---

## 三、本次整改后**保留的"问题"**（不动）

这些是已知问题，但属于"改了就是改逻辑"的范畴，阶段 4 **不动**。Kris 后续单独建 issue 修。

### 3.1 日志级别使用过度
许多分页进度类日志用了 `logger.info`，生产环境会很吵。例如：
```python
# xiezhi_http.py:400-404
logger.info(f"调用 FAQ PAGE 总记录数为:{total}，共{pages}页")
logger.info(f"正在获取第 {page} 页数据...")  # 每页一条
```
**第一轮不改**。第二轮单独开 PR 调级别（info → debug）。

### 3.2 用户原始 query 直接打日志（无脱敏）
```python
# intent_classifier_advance.py:252
logger.info(f"用户输入-{query},历史-{history}")

# nav_agent.py:42
logger.info(f"msg_id = {request.msg_id}, Request Payload = {request}")
```
- 项目里**已经有** `DataMaskingService`（core/services/data_masking_service.py）
- 但这些日志没接入脱敏
- **第一轮不接**：在日志前插脱敏调用属于改逻辑（多了一个异步调用 + 性能影响）
- 单独建 issue（**严重度高，金融行业合规要求**）

### 3.3 中文 vs 英文混用
```python
logger.info(f"用户输入-{query},历史-{history}")          # 中文
logger.info(f"Calling large model with {request_id}")    # 英文
```
**第一轮不动**——文本统一是新建一致性的事，不应在结构整改阶段做。

---

## 四、阶段 4 文件清单（执行顺序）

按"风险从低到高 / 影响从核心到边缘"排序：

### P0：核心基础设施（必须先做，影响下游所有日志）

| # | 文件 | 主要改动 |
|---|------|---------|
| 4.1 | `serve_app.py` | 47 处 print（启动 banner）→ logger.info |
| 4.2 | `core/utils/trace_id_middleware.py` | 4 处 print → logger（**修复 trace_id 透传**）|
| 4.3 | `core/utils/nav_logger.py` 的 `print_execution_time` 装饰器 | 4 处 print → 装饰器内 logger |

### P1：业务热点（影响主链路日志）

| # | 文件 | 主要改动 |
|---|------|---------|
| 4.4 | `core/services/xiezhi_http.py` | 检查是否有 print；不动 logger.info 级别 |
| 4.4 | `domains/shouxian/agents/nav_agent.py:51` | `traceback.print_exc()` → `exc_info=True` |
| 4.4 | `domains/yanglaoxian/agents/ylx_nav_agent.py:108,153,171` | 同上 |
| 4.4 | `domains/shouxian/services/shouxian_nav_service.py:317,345` | 同上 |

### P2：长尾（剩余文件）

| # | 范围 | 主要改动 |
|---|------|---------|
| 4.5 | scripts/ 目录所有 print（`scheduled_knowledge_sync.py`、`init_knowledge.py`） | print → logger（脚本也用 nav_logger） |
| 4.5 | 全局剩余的 `print(`、`traceback.print_exc()`、`logging.getLogger`、`import logging`（被替换后的死 import）| 收尾扫除 |

### 4.6 验收

- 全局 grep `print\(` 在 src/ 下应只剩 0 处（除字符串里的 "print"）
- 全局 grep `traceback.print_exc` 应是 0 处
- 全局 grep `import traceback` 应是 0 处（除非 traceback 还有其他用法）
- 全局 grep `logging.getLogger` 应是 0 处
- 全局 grep `import logging` 应只剩 nav_logger.py 自己（它要配置 root logger）

---

## 五、回归风险评估

阶段 4 的改动**不会改变任何业务行为**，但有一处细微差异需要 Kris 知道：

### 5.1 trace_id 在中间件层从无到有
之前 `trace_id_middleware.py` 用 print，trace_id 没注入到日志。修复后中间件那一段日志（请求开始 / 结束）会**新出现 trace_id 字段**。
- ✅ 这不是 bug，是修复。下游业务日志已经有 trace_id 了，只是中间件层之前断了。
- ⚠️ 如果有运维基于"中间件日志没有 trace_id"做了某种 grep 规则，要同步通知。

### 5.2 `print_execution_time` 装饰器输出格式改变
之前格式：`[INFO] func_name 执行耗时: 0.1234 秒, params: {...}`
之后格式：structlog 渲染（带颜色、时间戳、trace_id）

- ✅ 这是预期的统一化。
- ⚠️ 如果有 grep 规则按 `[INFO]` 前缀过滤，要同步通知。

### 5.3 `import logging` 改为 `get_logger` 的影响
原代码里几处 `logging.getLogger(__name__)` 拿的是标准 logger，输出到 root logger。现在改 `get_logger(__name__)` 用 structlog。
- 内容上等价，但**结构化输出格式**会从纯文本变成 structlog 渲染（开发环境带颜色、生产环境带 JSON）。
- 这取决于 `setup_logging(log_format=...)` 的设置 —— 与之前 `setup_logging` 的行为一致，无变化。
