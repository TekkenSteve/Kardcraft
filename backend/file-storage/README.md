# File Storage Service

基于 go-cloud blob 的灵活文件存储服务，支持多种存储后端和中间件功能。

## 特性

### 存储后端支持
- **MinIO** - S3 兼容的对象存储
- **AWS S3** - Amazon Simple Storage Service
- **Google Cloud Storage** - Google 云存储
- **Azure Blob Storage** - Microsoft Azure 存储
- **本地文件系统** - 用于开发和测试
- **内存存储** - 用于测试

### 中间件功能
- **审计日志** - 记录所有存储操作
- **数据压缩** - 自动压缩文件以节省空间
- **数据加密** - AES-GCM 加密保护敏感数据
- **缓存** - 内存缓存提高读取性能

### 策略引擎
- **文件大小限制** - 控制上传文件的最大大小
- **文件类型限制** - 限制允许的文件扩展名
- **内容类型验证** - 验证文件的 MIME 类型

## 快速开始

### 1. 安装依赖

```bash
# 安装 Buf（用于 protobuf lint/generate）
# https://buf.build/docs/installation

# 安装 Go 工具
make install-tools
```

### 2. 生成 Protobuf 代码

```bash
make proto
```

### 3. 构建服务

```bash
make build
```

### 4. 运行服务

```bash
# 使用默认配置运行
make run

# 或者直接运行二进制文件
./bin/storage
```

### 5. 测试服务

```bash
# 运行示例客户端
go run examples/client/main.go

# 检查服务健康状态
make health
```

## 配置

服务通过 `config.yaml` 文件进行配置。主要配置项包括：

### 服务器配置
```yaml
server:
  port: "50053"
  host: "0.0.0.0"
```

### 存储配置
```yaml
storage:
  default_provider: "minio"
  providers:
    minio:
      endpoint: "minio:9000"
      access_key: "minioadmin"
      secret_key: "minioadmin"
      secure: false
      bucket: "kardcraft-files"
```

### 中间件配置
```yaml
middleware:
  audit:
    enabled: true
  compression:
    enabled: true
    algorithm: "gzip"
  encryption:
    enabled: false
    key: "your-32-byte-encryption-key-here"
  cache:
    enabled: true
    ttl: "1h"
    max_size: "100MB"
```

### 策略配置
```yaml
policies:
  max_file_size: "100MB"
  allowed_extensions: [".jpg", ".jpeg", ".png", ".gif", ".pdf", ".txt"]
```

## 开发

### 开发模式运行
```bash
make dev
```

### 运行测试
```bash
make test
make test-coverage
```

### 代码格式化和检查
```bash
make fmt
make lint
```

## Docker

### 构建镜像
```bash
make docker-build
```

### 运行容器
```bash
make docker-run
```

## API 文档

服务提供以下 gRPC 接口：

- `Upload` - 上传文件（流式）
- `Download` - 下载文件（流式）
- `Delete` - 删除文件
- `Exists` - 检查文件是否存在
- `List` - 列出文件
- `GetMetadata` - 获取文件元数据
- `UpdateMetadata` - 更新文件元数据
- `GeneratePresignedURL` - 生成预签名 URL
- `GetHealth` - 健康检查

详细的 API 定义请参考 `backend/protobuf/file_storage.proto` 文件。

## 架构设计

### 设计模式
- **适配器模式** - 统一不同存储后端的接口
- **工厂模式** - 动态创建存储实例
- **策略模式** - 支持不同的存储策略
- **中间件模式** - 支持插件化功能
- **依赖注入** - 解耦组件依赖

### 组件结构
```
internal/
├── config/          # 配置管理
├── storage/         # 存储接口和实现
│   └── providers/   # 各种存储提供商
├── middleware/      # 中间件实现
├── policy/          # 策略引擎
└── service/         # gRPC 服务实现
```

## 环境变量

可以通过环境变量覆盖配置文件中的设置：

- `PORT` - 服务端口
- `HOST` - 服务主机
- `STORAGE_PROVIDER` - 默认存储提供商
- `MINIO_ENDPOINT` - MinIO 端点
- `MINIO_ACCESS_KEY` - MinIO 访问密钥
- `MINIO_SECRET_KEY` - MinIO 密钥

## 许可证

MIT License
