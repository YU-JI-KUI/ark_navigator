# Super Agent Ark-Nav 服务

基于Ray的高并发AI服务，支持训练、推理，和智能体的搭建

## 架构

```
Ray Serve集群
├── 模型层（GPU自动扩展）
│   ├── BGE-base-zh-1.5 (Embedding)
│   ├── BGE-reranker-base（重排序）
│   ├── BERT-base（如寿险BERT意图识别模型）
│   └── ...其他模型可按需配置
├── 业务层（CPU多副本自动扩展）
│   ├── VectorStore（FAISS知识库检索）
│   ├── 大模型平台API直接调用（如：寿险小模型）
│   └── HyperAPI（多层：检索+BERT+808）
└── API层（HTTP入口）
```

## 核心功能

### 寿险万能服务

- 意图识别API
- 小导航智能体代码化
- 寿险Agentic Flow（TBD）

### 养老险万能服务

- TBD

---

## 快速开始

### 安装

```bash
# 安装uv
pip install uv

# 查看uv的安装路径
pip show uv

# 添加uv路径（D:\Users\YUJIKUI772\AppData\Roaming\Python\Python312\site-packages）到Path环境变量，验证是否安装成功
uv --version

# 安装依赖
uv sync
```

### 初始化知识库 - 按需

```bash
python scripts/init_knowledge.py
```

### 配置环境变量

```bash
cp .env.example .env
# 编辑.env配置LLM API地址
```

### 启动服务

**Step 0：配置本地 env**

**Step 1：启动本地Ray服务集群**

```bash
cd ark_navigator

source .venv/Scripts/activate

# 启动Ray本地集群
ray start --head --dashboard-host=0.0.0.0 --dashboard-port=8265 --include-dashboard=true --ray-client-server-port=10001 --disable-usage-stats

# 验证Ray状态
ray status
```

**Step 2：加载业务Ray Deployment**

```bash
# 方式1：直接启动
uv pip install -e .

python -m ark_nav.serve_app

# 方式2：使用命令行（需先安装）
serve

# 方式3：使用Ray CLI
serve run ark_nav.serve_app:build_app
```

### 访问

- 服务地址：http://localhost:8000
- API文档：http://localhost:8000/docs
- Ray Dashboard：http://localhost:8265（监控面板）

---

## 监控

启动服务后访问 Ray Dashboard：http://localhost:8265

### 核心页面

- **Serve**：查看部署状态、QPS、延迟、自动扩展
- **Actors**：查看GPU/CPU使用率、内存占用
- **Metrics**：Prometheus格式指标，可接入Grafana

### 性能指标

| 指标 | 说明 |
|------|------|
| `serve_deployment_request_counter` | 请求计数 |
| `serve_deployment_processing_latency_ms` | 处理延迟 |
| `serve_deployment_queued_queries` | 队列长度 |
| `serve_num_deployment_replicas` | 副本数量 |

---

## 测试

（待补充）

---

## 配置

### 环境变量

服务的所有环境变量分组列在 **[docs/ENVIRONMENT.md](docs/ENVIRONMENT.md)** 中，包含必填性、默认值、示例和说明。

快速参考：

- **本地开发**：复制 `.env.sample` 为 `.env`，按 `docs/ENVIRONMENT.md` 的"最小启动示例"填写关键字段
- **生产部署**：通过容器编排注入环境变量；必填项缺失会导致服务启动失败
- **新增/删除变量**：必须同步更新 `docs/ENVIRONMENT.md`，避免文档漂移

### GPU要求

- V100 16GB（生产环境）
- 本地开发支持CPU模式

---

## 性能

**寿险意图识别大模型直调：**
- 延迟：300-600ms
- 吞吐：TBD QPS

**寿险意图识别多层混合方案（测试环境）：**
- 命中知识库：~15ms
- 知识库排排：~18ms
- BERT意图识别：~12ms
- 吞吐：TBD QPS

GPU显存：~5GB / 16GB

---

## License

MIT
