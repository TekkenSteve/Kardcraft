# Event Pipeline Audit (Task-Orchestrator + Agent-Workflow + Frontend)

## Scope
- 仅审查「任务执行事件」链路：
  - `agent-workflow` 事件产生
  - `task-orchestrator` Redis/SSE/Timeline 持久化
  - frontend timeline 实时与历史消费
- 本文档不包含功能新增，只记录当前问题与收敛方向。

## Current End-to-End Flow
1. `task-orchestrator` 启动 Temporal `TaskWorkflow`，执行 `execute_agent_workflow`。  
   - `backend/task-orchestrator/internal/infrastructure/temporal/workflows/task_workflow.go:127`
2. `agent-workflow` `WorkflowManager` 将 LangGraph `updates` 转换为节点生命周期事件：  
   - `NODE_STARTED` / `NODE_COMPLETED` / `NODE_FAILED`（包含 `node_output` payload）  
   - `backend/agent-workflow/src/kardcraft/workflow/manager.py:223`
3. `AgentActivities._publish_progress_event` 写入 Redis Stream `stream:events:{task_id}`。  
   - `backend/agent-workflow/src/kardcraft/temporal/activities/agent_activities.py:402`
4. `task-orchestrator` SSE 连接时启动 `subscribeRedisStream` 读同一 stream，`appendTimeline` 后写入 `kc_events`。  
   - `backend/task-orchestrator/internal/infrastructure/http/server.go:1343`  
   - `backend/task-orchestrator/internal/infrastructure/http/server.go:1394`  
   - `backend/task-orchestrator/internal/infrastructure/http/server.go:507`
5. frontend 同时消费：
   - SSE 实时事件（`useRunStream`）  
     - `frontend/lib/kardcraft/stream.ts:172`
   - `/api/v1/sessions/{id}/timeline` 历史事件（默认 `include_payload=false`）  
     - `frontend/lib/kardcraft/api.ts:698`

## Findings

### Critical
1. **事件回路风险（读-写同流）**
- `InsertEvent` 成功后再次 `XADD stream:events:{workflow}`，而该 stream 正被 `subscribeRedisStream` 消费并再写库。  
- 容易造成事件放大、重复持久化、时间线膨胀。
- 位置：
  - `backend/task-orchestrator/internal/infrastructure/persistence/session_store.go:747`
  - `backend/task-orchestrator/internal/infrastructure/http/server.go:1394`
- 解决方法：
  - 从 `InsertEvent` 删除 `XADD stream:events:{workflow}` 回写逻辑，`kc_events` 只做持久化，不再反向写 realtime stream。
  - 规定唯一实时入口：只允许 `agent-workflow`（或统一事件总线）写 `stream:events:*`。
  - 增加保护：若未来确需双写，使用不同 stream 命名空间（例如 `stream:timeline:*`）避免闭环。

2. **每个 SSE 连接都启动一个 Redis 消费协程**
- 每次连接调用 `go subscribeRedisStream(...)`。
- 多个前端连接会并发重复消费同一 workflow stream。
- 位置：
  - `backend/task-orchestrator/internal/infrastructure/http/server.go:1343`
- 解决方法：
  - 把 stream 消费器从 `sseHandler` 移出，改为服务级单例消费者（按 workflow 维度复用）。
  - 用 `sync.Map + singleflight` 或显式 registry，确保同一 workflow 仅启动一个 reader。
  - SSE handler 只做订阅内存广播通道，不负责启动/停止 Redis reader。

3. **Redis Stream 消费从 `0` 开始**
- `lastID := "0"` 导致每个新消费者从头读完整历史，重复推送 + 重复入库。
- 位置：
  - `backend/task-orchestrator/internal/infrastructure/http/server.go:1399`
- 解决方法：
  - 首次消费使用 `$`（只读新消息），禁止连接时从 `0` 回放。
  - 若需要可恢复消费，持久化每 workflow 的 checkpoint（last stream id），服务重启后从 checkpoint 继续。
  - 历史回放统一由 `kc_events` API 提供，不走 Redis 全量重读。

4. **前后端事件合同不一致（实时事件丢失）**
- 后端主推 `NODE_STARTED/NODE_COMPLETED/NODE_FAILED`，frontend 若未同步监听会导致实时缺失。
- 位置：
  - 生产端：`backend/agent-workflow/src/kardcraft/workflow/manager.py:240`
  - 消费端：`frontend/lib/kardcraft/stream.ts:179`
- 解决方法：
  - 更新前端监听列表，加入 `NODE_STARTED/NODE_COMPLETED/NODE_FAILED`。
  - 更新 `types.ts` 事件类型定义，只保留生命周期事件。
  - 约束事件合同文档：节点事件必须携带 `node_name + payload + workspace_id(可选)`。

### High
5. **frontend 状态/去重逻辑未完全迁移生命周期事件**
- 运行状态条与去重核心必须统一到 `NODE_STARTED/NODE_COMPLETED/NODE_FAILED`。
- 位置：
  - `frontend/lib/features/runSlice.ts:129`
  - `frontend/lib/features/runSlice.ts:247`
- 解决方法：
  - 将状态 pill 与去重键迁移到生命周期事件：`workflow_id + node_name + phase`。
  - `running` 仅由 `NODE_STARTED` 触发；`completed/failed` 由对应结束事件触发。
  - 删除 `node is working` 推断分支，消息由后端事件 payload/message 直接提供。

6. **SSE backlog 内存无上限**
- `timelineByWorkflow` 持续 append 且连接时全量回放，历史多时首屏/展开 timeline 负担大。
- 位置：
  - `backend/task-orchestrator/internal/infrastructure/http/server.go:539`
  - `backend/task-orchestrator/internal/infrastructure/http/server.go:1358`
- 解决方法：
  - 给 `timelineByWorkflow` 增加固定上限（例如 300~500），超出即裁剪旧事件。
  - SSE 连接时只回放最近 N 条内存事件；完整历史由 `/sessions/{id}/timeline` 拉取。
  - 为 timeline payload 加大小上限与裁剪策略，避免单事件超大导致卡顿。

7. **workspace 抽象被 session 回填覆盖**
- 读取到 `workspace_id` 后，后续又以 `task->session` 结果覆盖，抽象隔离被弱化。
- 位置：
  - `backend/task-orchestrator/internal/infrastructure/http/server.go:1496`
- 解决方法：
  - 明确优先级：`workspace_id` > `task->session` 推导值。
  - 仅在 `workspace_id` 缺失时才 fallback 到 `session_id`。
  - 数据模型上增加 `workspace_id` 字段（events/session-view DTO），避免语义丢失。

### Medium
8. **历史接口默认不返回 payload**
- timeline API 默认 `include_payload=false`，导致历史查看时细节为空，和“要看到 payload”诉求冲突。
- 位置：
  - `frontend/lib/kardcraft/api.ts:698`
  - `backend/task-orchestrator/internal/infrastructure/http/server.go:1771`
- 解决方法：
  - 前端默认 `include_payload=true`（至少 timeline 详情页默认开启）。
  - 后端支持“摘要 + 展开详情”模式：列表默认返回 payload 摘要，详情接口返回完整 payload。
  - 为 payload 返回增加体积保护（字段裁剪/截断标记）。

9. **疑似残留接口**
- `publish_workflow_event` activity 已定义，但当前主路径未见调用，容易造成理解负担。
- 位置：
  - `backend/agent-workflow/src/kardcraft/temporal/activities/agent_activities.py:363`
- 解决方法：
  - 二选一：  
    - 若不再使用：删除 `publish_workflow_event` 及其注册，减少认知负担。  
    - 若保留：在文档标注用途（人工补发/系统事件）并补充调用路径与测试。
  - 统一只保留一个主事件发布 API，避免双入口。

## Code Quality Assessment

### 是否有无效代码
- 有：
  - 未接入主链路的事件发布接口（`publish_workflow_event`）。
  - 若仍存在遗留节点进度事件类型，会造成合同分叉。

### 逻辑表达是否清晰简明
- 当前不够简明：
  - 事件生产与消费两端都存在较多兜底/回退分支，语义边界不集中。
  - 同一事件在多个层次被重复加工，增加维护成本。

### 是否滥用兜底
- 存在明显滥用倾向：
  - 生产端、桥接层、前端都在做“消息猜测与兜底拼装”。
  - 应收敛为：生产端定义清晰合同，消费端只做轻量展示转换。

## Recommended Refactor Principles
1. **单一事件真相源**
- 生命周期事件在生产端（agent-workflow）一次定义清楚，避免下游猜测。

2. **禁止读写同一实时流形成闭环**
- Timeline 持久化与实时推送分离，避免消费者回写原始输入流。

3. **一个 workflow 一个消费者（或消费者组）**
- 避免按 SSE 连接数扩容消费协程。

4. **workspace-first 隔离**
- `workspace_id` 作为通用隔离凭证，`session_id` 仅作为当前实现的一种凭证值，不在通道语义中硬编码。

5. **前后端事件合同同步升级**
- frontend 监听、状态映射、去重规则与后端真实事件类型保持一致。

6. **统一 Redis 访问层（task-orchestrator）**
- 在 `task-orchestrator` 引入类似 `agent-workflow/src/kardcraft/services/redis.py` 的统一 Redis service，收敛 stream/cache/pubsub 访问逻辑，避免散落在 handler/store 中各自实现。

## Redis Service Layer Proposal (Task-Orchestrator)

### 为什么要加（回答：是，建议加）
- 可以一次性解决：连接管理、重试策略、stream 读写约束、key 命名规范、metrics/tracing、错误分类。
- 能显著减少当前“HTTP 层 + persistence 层都在直接调 redis”的重复与分叉。
- 便于落地前述关键修复：单消费者、checkpoint、禁止闭环写回。

### 建议接口（示意）
- `StreamRead(ctx, workflowID, fromID, count, block) ([]Event, nextID, error)`
- `StreamAppend(ctx, workflowID, event) (streamID, error)`（仅允许特定调用方）
- `PublishSSE(ctx, workflowID, payload) error`（若仍需 pub/sub）
- `SetCheckpoint/GetCheckpoint(ctx, workflowID) (string, error)`
- `CacheGet/CacheSet/CacheDel(ctx, key, ttl, value)`

### 约束策略
- 约束 1：`kc_events` 持久化路径禁止写入 `stream:events:*`。
- 约束 2：stream 读取默认从 `$` 或 checkpoint，禁止默认 `0`。
- 约束 3：所有 redis key 走统一 builder，显式区分 `workspace` 与 `session`。

## Implementation Status (2026-03-16)
- [x] 去除 `kc_events -> Redis stream:events:{workflow}` 回写路径
- [x] 引入统一 Redis service 层（`internal/infrastructure/redis/service.go`）
- [x] `subscribeRedisStream` 改为 workflow 级 reader（不再每个 SSE 连接单独起 reader）
- [x] Redis 读取游标改为 `$ / checkpoint` 增量消费（移除默认 `0` 全量回放）
- [x] frontend `stream.ts` 监听 `NODE_STARTED/NODE_COMPLETED/NODE_FAILED`
- [x] frontend `runSlice` 统一到生命周期事件（移除 `NODE_UPDATE`）
- [x] timeline 历史默认返回 payload（前后端默认开启）
- [x] `timelineByWorkflow` / `timelineBySession` 增加内存上限裁剪
- [x] workspace 优先于 session fallback（仅缺失 workspace 时才回退 task->session）
- [x] 落库幂等保护：按 `(session_id, stream_id)` 进行重复写入保护
- [x] 去除事件链路内存兜底：`workflowHistory` 在非 Temporal 模式改为查询 `kc_events`（不再读内存 timeline）
- [x] 去除任务状态/取消内存兜底：`workflowStatus` / `workflowCancel` 在非 Temporal 模式返回 `503`（不再走 in-memory task service）
- [x] 去除模板接口内存兜底：`card-templates` 与 `template-preferences` 仅读 DB；写接口不再写内存 map
- [x] 去除任务创建内存会话镜像：删除 `ensureSession/attachTaskToSession` 路径与对应内存状态更新
- [x] 统一 Redis 访问层落地到 persistence：`task/session/workspace/cache` 键读写与失效统一走 `internal/infrastructure/redis/service.go`

## Remaining Optional Hardening
- [x] 在 DB 层新增唯一索引 `UNIQUE(workflow_id, stream_id)`（`kc_events`）
- [x] 补充自动化测试：stream reader lifecycle、event dedupe、timeline payload contract
- [x] 为 Redis service 增加 metrics/tracing（读延迟、重复丢弃数、checkpoint lag）
