# Kardcraft Agent Workflow

Agent工作流层 (Python + LangGraph) - gRPC服务器实现

## 概述

Agent Workflow是Kardcraft系统的AI工作流层，负责：
- 执行复杂的工作流（使用LangGraph）
- 管理用户工作空间
- 统一安全执行（Monty快路径 + 容器沙箱兜底）
- 处理文档处理和卡片生成任务

## 架构

```
┌─────────────────┐
│   Go Orchestrator  │ (任务编排层)
│   (gRPC Server)    │
└─────────┬─────────┘
          │ gRPC
┌─────────▼─────────┐
│   Agent Workflow   │ (AI工作流层)
│   (gRPC Server)    │
└─────────┬─────────┘
          │ Execution Service
┌─────────▼─────────┐
│ Container Sandbox  │ (默认隔离执行层)
│ + Monty Fast Lane  │ (受限快路径)
└───────────────────┘
```

## 功能特性

### 1. 工作流管理
- 基于LangGraph的工作流引擎
- 支持检查点和恢复
- 异步任务执行
- 进度监控和状态查询

### 2. 工作空间服务
- 用户隔离的工作空间
- 文件上传/下载管理
- MinIO对象存储集成
- PostgreSQL元数据存储

### 3. 服务集成
- Redis缓存和状态管理
- 执行路由与策略控制
- 健康检查和监控

### 4. 配置管理
- 环境变量配置
- Pydantic设置验证
- 多环境支持

## 快速开始

### 环境要求
- Python 3.9+
- Redis 6.0+
- PostgreSQL 13+
- MinIO (可选)
- Docker + gVisor(runsc) (推荐)

### 安装

1. 克隆项目：
```bash
git clone <repository-url>
cd backend/agent-workflow
```

2. 创建虚拟环境：
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows
```

3. 安装依赖：
```bash
pip install -e .
```

### 配置

`agent-workflow` 运行时仅支持仓库根目录分层 env：

- `/home/embedfire/Kardcraft/.env.runtime`
- `/home/embedfire/Kardcraft/.env.llm`
- `/home/embedfire/Kardcraft/.env.ragix`

不再使用 `backend/agent-workflow/.env*` 作为运行时配置源。

关键要求：

- 使用 canonical 键名，不保留运行时别名。
- `dotenv` 仅在进程入口统一加载一次，业务模块不做隐式加载。

### 运行

1. 启动服务器：
```bash
python -m kardcraft.grpc.server
```

2. 或使用入口点：
```bash
agent-workflow
```

### 测试

运行单元测试：
```bash
pytest tests/
```

## API文档

### gRPC服务

#### PythonWorkflow服务

```protobuf
service PythonWorkflow {
    // 执行工作流
    rpc ExecuteWorkflow(WorkflowRequest) returns (WorkflowResponse);

    // 恢复工作流（从Checkpoint）
    rpc ResumeWorkflow(ResumeRequest) returns (WorkflowResponse);

    // 获取工作流状态
    rpc GetWorkflowStatus(WorkflowStatusRequest) returns (WorkflowStatusResponse);

    // 健康检查
    rpc HealthCheck(HealthCheckRequest) returns (HealthCheckResponse);
}
```

#### 主要消息类型

1. **WorkflowRequest** - 工作流执行请求
   - `task_id`: 任务ID
   - `user_id`: 用户ID
   - `task_type`: 任务类型（document_processing, card_generation等）
   - `config`: 配置参数
   - `input`: JSON格式输入数据
   - `workspace`: 用户工作空间配置
   - `checkpoint_id`: 可选的检查点ID

2. **WorkflowResponse** - 工作流响应
   - `task_id`: 任务ID
   - `status`: 状态（completed, failed, timeout）
   - `result`: JSON格式结果
   - `error`: 错误信息（如果有）
   - `checkpoint_id`: 创建的检查点ID
   - `execution_time_ms`: 执行时间（毫秒）
   - `generated_cards`: 生成的卡片列表

### 客户端示例

```python
import grpc
import kardcraft_pb2
import kardcraft_pb2_grpc

# 创建gRPC通道
channel = grpc.insecure_channel('localhost:50051')
stub = kardcraft_pb2_grpc.PythonWorkflowStub(channel)

# 执行工作流
request = kardcraft_pb2.WorkflowRequest(
    task_id="task-123",
    user_id="user-456",
    task_type="document_processing",
    config={"language": "zh"},
    input='{"document_url": "https://example.com/doc.pdf"}'
)

response = stub.ExecuteWorkflow(request)
print(f"Status: {response.status}")
print(f"Result: {response.result}")
```

## 工作流类型

### 1. 文档处理工作流
- PDF/Word/Excel文档解析
- 文本提取和清理
- 内容分块和标记
- 元数据提取

### 2. 卡片生成工作流
- 从文本生成闪卡
- 难度级别评估
- 标签分类
- 质量检查

### 3. 知识嵌入工作流
- 文本向量化
- 向量存储
- 相似性搜索
- 知识图谱构建

## 监控和日志

### 日志级别
- INFO: 常规操作日志
- WARNING: 警告信息
- ERROR: 错误信息
- DEBUG: 调试信息（开发环境）

### 健康检查
```bash
# 使用grpcurl检查健康状态
grpcurl -plaintext localhost:50051 kardcraft.PythonWorkflow/HealthCheck
```

### 指标监控
- 活跃工作流数量
- 平均执行时间
- 成功率/失败率
- 资源使用情况

## 部署

### Docker部署

```dockerfile
FROM python:3.9-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY pyproject.toml .
COPY README.md .
COPY src/ ./src/

# 安装Python依赖
RUN pip install --no-cache-dir -e .

# 运行服务
CMD ["agent-workflow"]
```

### Kubernetes部署

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agent-workflow
spec:
  replicas: 3
  selector:
    matchLabels:
      app: agent-workflow
  template:
    metadata:
      labels:
        app: agent-workflow
    spec:
      containers:
      - name: agent-workflow
        image: kardcraft/agent-workflow:latest
        ports:
        - containerPort: 50051
        env:
        - name: REDIS_HOST
          value: "redis-service"
        - name: POSTGRES_HOST
          value: "postgres-service"
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1"
```

## 开发指南

### 项目结构
```
agent-workflow/
├── src/kardcraft/
│   ├── grpc/          # gRPC服务器实现
│   │   ├── __init__.py
│   │   └── server.py  # 主服务器
│   ├── workflow/      # 工作流管理
│   │   ├── __init__.py
│   │   └── manager.py # 工作流管理器
│   ├── workspace/     # 工作空间服务
│   │   ├── __init__.py
│   │   └── service.py # 工作空间服务
│   ├── services/      # 外部服务客户端
│   │   ├── __init__.py
│   │   ├── rust_client.py  # Rust服务客户端
│   │   └── redis_client.py # Redis客户端
│   └── __init__.py
├── tests/             # 测试文件
├── pyproject.toml     # 项目配置
├── README.md          # 本文档
└── .env.example       # DEPRECATED: 使用仓库根目录分层 env
```

### 添加新工作流

1. 创建工作流图：
```python
# src/kardcraft/workflow/new_workflow.py
from langgraph.graph import StateGraph

class NewWorkflowGraph:
    def __init__(self, config, services):
        self.config = config
        self.services = services

    async def build(self):
        graph = StateGraph()
        # 添加节点和边
        return graph
```

2. 在工作流管理器中注册：
```python
# 在manager.py的_initialize_graphs方法中添加
new_graph = NewWorkflowGraph(config, services)
self.graphs["new_workflow"] = await new_graph.build()
```

### 测试新功能

1. 编写单元测试：
```python
# tests/test_new_workflow.py
import pytest
from kardcraft.workflow.new_workflow import NewWorkflowGraph

@pytest.mark.asyncio
async def test_new_workflow():
    # 测试代码
    pass
```

2. 运行测试：
```bash
pytest tests/test_new_workflow.py -v
```

## 故障排除

### 常见问题

1. **gRPC连接失败**
   - 检查端口是否被占用
   - 验证网络连接
   - 检查防火墙设置

2. **Redis连接失败**
   - 验证Redis服务是否运行
   - 检查认证信息
   - 确认网络可达性

3. **工作流执行超时**
   - 增加超时时间
   - 检查资源使用情况
   - 优化工作流逻辑

4. **内存泄漏**
   - 监控内存使用
   - 定期重启服务
   - 优化数据处理

### 调试模式

启用调试日志：
```bash
export LOG_LEVEL=DEBUG
agent-workflow
```

## 性能优化

### 建议配置

1. **gRPC设置**
   - 调整最大消息大小
   - 优化连接池大小
   - 配置keepalive参数

2. **工作流优化**
   - 使用检查点减少重复计算
   - 并行处理独立任务
   - 缓存频繁访问的数据

3. **资源管理**
   - 限制并发工作流数量
   - 监控内存使用
   - 定期清理临时文件

## 贡献指南

1. Fork项目
2. 创建功能分支
3. 提交更改
4. 推送分支
5. 创建Pull Request

## 许可证

MIT License

## 支持

- 问题报告：[GitHub Issues](https://github.com/kardcraft/kardcraft/issues)
- 文档：[项目Wiki](https://github.com/kardcraft/kardcraft/wiki)
- 讨论：[GitHub Discussions](https://github.com/kardcraft/kardcraft/discussions)
