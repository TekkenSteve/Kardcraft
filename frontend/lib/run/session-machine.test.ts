/**
 * 新 session-machine 的事件驱动流测试
 *
 * 验证：
 * - applyDomainEvent 正确更新消息和控制状态
 * - START_WORKFLOW 创建 generating 占位消息
 * - message.delta 正确追加内容
 * - message.completed 正确终结消息
 * - 终端事件清理 streaming/generating 标记
 * - 暂停/继续/取消流
 * - workspace.updated 更新卡片
 */

import { describe, expect, it } from 'vitest';
import { createActor } from 'xstate';
import { createSessionMachine } from './session-machine';
import type { RuntimeEnvelope } from './runtime-envelope';

const makeEnvelope = (overrides: Partial<RuntimeEnvelope> & { event_type: string }): RuntimeEnvelope => ({
  schema_version: 1,
  correlation_id: 'corr-test',
  event_id: `evt-${Date.now()}`,
  occurred_at: new Date().toISOString(),
  workflow_id: 'wf-1',
  run_id: 'run-1',
  session_id: 's-1',
  payload: {},
  ...overrides,
});

const createTestActor = () => {
  const actor = createActor(createSessionMachine());
  actor.start();
  return actor;
};

const getContext = (actor: ReturnType<typeof createTestActor>) => {
  return actor.getSnapshot().context;
};

describe('session machine event-driven flow', () => {
  it('creates generating placeholder on START_WORKFLOW', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', runId: 'run-1', query: 'hello' });

    const ctx = getContext(actor);
    expect(ctx.status).toBe('running');
    expect(ctx.workflowId).toBe('wf-1');
    // 应有 user 消息 + generating 占位
    expect(ctx.messages.length).toBe(2);
    expect(ctx.messages[0].role).toBe('user');
    expect(ctx.messages[0].content).toBe('hello');
    expect(ctx.messages[1].role).toBe('assistant');
    expect(ctx.messages[1].isGenerating).toBe(true);
  });

  it('hydrates existing messages without adding a duplicate placeholder', () => {
    const actor = createTestActor();
    actor.send({
      type: 'HYDRATE',
      workflowId: 'wf-1',
      runId: 'run-1',
      messages: [
        { id: 'existing-1', role: 'user', content: 'hello' },
        { id: 'existing-2', role: 'assistant', content: 'answer', taskId: 'wf-1' },
      ],
      events: [],
      cards: [],
      state: { active_task_id: 'wf-1', task_state: 'SUCCEEDED' },
    });

    const ctx = getContext(actor);
    expect(ctx.messages.length).toBe(2);
    expect(ctx.messages[0].id).toBe('existing-1');
    expect(ctx.messages.some((message) => message.isGenerating)).toBe(false);
  });

  it('message.delta appends content to streaming message', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', query: 'hello' });

    // 先定位 generating 消息的 ID
    let ctx = getContext(actor);
    const genMsg = ctx.messages.find(m => m.isGenerating)!;
    expect(genMsg).toBeDefined();

    // 发送 SSE 信封 → 通过 SSE_ENVELOPE 管道触发 applyDomainEvent
    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'thread.message.delta',
        workflow_id: 'wf-1',
        event_id: 'delta-1',
        payload: { delta: 'Hello, ' },
      }),
    });

    // applyDomainEvent 找到 generating 消息并替换为 delta
    ctx = getContext(actor);
    const deltaMsg = ctx.messages.find(m => m.id === 'delta-1');
    expect(deltaMsg).toBeDefined();
    expect(deltaMsg!.content).toBe('Hello, ');
    expect(deltaMsg!.isStreaming).toBe(true);
    expect(deltaMsg!.isGenerating).toBe(false);
    // generating 占位不应存在
    expect(ctx.messages.find(m => m.isGenerating)).toBeUndefined();

    // 第二条 delta 追加
    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'thread.message.delta',
        workflow_id: 'wf-1',
        event_id: 'delta-1',
        payload: { delta: 'world!' },
      }),
    });

    ctx = getContext(actor);
    expect(ctx.messages.find(m => m.id === 'delta-1')!.content).toBe('Hello, world!');
  });

  it('message.completed finalizes message content', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', query: 'hello' });

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'thread.message.delta',
        workflow_id: 'wf-1',
        event_id: 'msg-1',
        payload: { delta: 'partial...' },
      }),
    });

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'thread.message.completed',
        workflow_id: 'wf-1',
        event_id: 'msg-1',
        payload: { content: 'Full response.' },
      }),
    });

    const ctx = getContext(actor);
    const msg = ctx.messages.find(m => m.id === 'msg-1');
    expect(msg).toBeDefined();
    expect(msg!.content).toBe('Full response.');
    expect(msg!.isStreaming).toBe(false);
    expect(msg!.isGenerating).toBe(false);
  });

  it('workflow.completed clears all streaming/generating flags', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', query: 'hello' });

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'thread.message.delta',
        workflow_id: 'wf-1',
        event_id: 'msg-1',
        payload: { delta: 'progress...' },
      }),
    });

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'workflow.completed',
        workflow_id: 'wf-1',
        event_id: 'done-1',
        payload: {},
      }),
    });

    const ctx = getContext(actor);
    expect(ctx.status).toBe('completed');
    expect(ctx.runPhase).toBe('hydrated');
    expect(ctx.messages.every(m => !m.isGenerating && !m.isStreaming)).toBe(true);
  });

  it('workflow.completed removes an empty assistant placeholder when no final text exists', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', query: 'hello' });

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'workflow.completed',
        workflow_id: 'wf-1',
        event_id: 'done-empty',
        payload: {},
      }),
    });

    const ctx = getContext(actor);
    expect(ctx.status).toBe('completed');
    expect(ctx.messages.some((message) => message.role === 'assistant' && message.content.trim().length === 0)).toBe(false);
  });

  it('timeline progress events use one status message slot and terminal events clear it', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', runId: 'run-1', query: 'hello' });

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'NODE_STARTED',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: 'progress-1',
        payload: { message: 'scope planner started', stream_id: 'progress-1' },
      }),
    });

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'NODE_COMPLETED',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: 'progress-2',
        payload: { message: 'scope planner completed', stream_id: 'progress-2' },
      }),
    });

    let ctx = getContext(actor);
    expect(ctx.events.some((event) => event.type === 'NODE_STARTED')).toBe(true);
    expect(ctx.messages.filter((message) => message.role === 'status')).toHaveLength(1);
    expect(ctx.messages.some((message) => message.role === 'status' && message.content === 'scope planner completed')).toBe(true);

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'workflow.completed',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: 'done-after-progress',
        payload: {},
      }),
    });

    ctx = getContext(actor);
    expect(ctx.messages.some((message) => message.role === 'status')).toBe(false);
  });

  it('hydrates running progress into one status slot and terminal hydration clears it', () => {
    const actor = createTestActor();
    actor.send({
      type: 'HYDRATE',
      workflowId: 'wf-1',
      runId: 'run-1',
      messages: [{ id: 'user-1', role: 'user', content: 'hello' }],
      events: [
        { id: 1, type: 'NODE_STARTED', workflow_id: 'wf-1', run_id: 'run-1', stream_id: 'p-1', message: 'scope planner started' },
        { id: 2, type: 'NODE_COMPLETED', workflow_id: 'wf-1', run_id: 'run-1', stream_id: 'p-2', message: 'scope planner completed' },
      ],
      cards: [],
      state: { active_task_id: 'wf-1', task_state: 'RUNNING', session_control_state: 'ACTIVE_RUNNING' },
    });

    let ctx = getContext(actor);
    expect(ctx.status).toBe('running');
    expect(ctx.messages.filter((message) => message.role === 'status')).toHaveLength(1);
    expect(ctx.messages.some((message) => message.role === 'status' && message.content === 'scope planner completed')).toBe(true);

    actor.send({
      type: 'HYDRATE',
      workflowId: 'wf-1',
      runId: 'run-1',
      messages: [{ id: 'user-1', role: 'user', content: 'hello' }],
      events: [
        { id: 3, type: 'WORKFLOW_COMPLETED', workflow_id: 'wf-1', run_id: 'run-1', stream_id: 'done-1', message: 'done' },
      ],
      cards: [],
      state: { active_task_id: 'wf-1', task_state: 'SUCCEEDED' },
    });

    ctx = getContext(actor);
    expect(ctx.status).toBe('completed');
    expect(ctx.messages.some((message) => message.role === 'status')).toBe(false);
    expect(ctx.messages.some((message) => message.role === 'assistant' && message.content.trim().length === 0)).toBe(false);
  });

  it('workflow.failed clears streaming flags and sets error', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', query: 'hello' });

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'workflow.failed',
        workflow_id: 'wf-1',
        event_id: 'fail-1',
        payload: { message: 'Something broke', code: 'INTERNAL' },
      }),
    });

    const ctx = getContext(actor);
    expect(ctx.status).toBe('failed');
    expect(ctx.runPhase).toBe('error');
    expect(ctx.streamError).toBe('Something broke');
    expect(ctx.messages.every(m => !m.isGenerating && !m.isStreaming)).toBe(true);
  });

  it('workspace.updated upserts cards', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', runId: 'run-1', query: 'hello' });
    const card1 = {
      id: 'c-1',
      user_id: 'u-1',
      card_id: 'card-1',
      content: { version: 1, model: 'gpt-4', data: { front: 'Q', back: 'A' } },
      edit_state: { status: 'draft' as const },
      concepts: [],
      meta: { created_at: '', modified_at: '', manual_edits: 0 },
    };

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'WORKSPACE_UPDATED',
        workflow_id: 'wf-1',
        event_id: 'ws-1',
        payload: {
          version: 1,
          cards: [card1],
        },
      }),
    });

    let ctx = getContext(actor);
    expect(ctx.cards.length).toBe(1);
    expect(ctx.cards[0].card_id).toBe('card-1');

    // upsert 同名卡片
    card1.content.data.front = 'Updated Q';
    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'WORKSPACE_UPDATED',
        workflow_id: 'wf-1',
        event_id: 'ws-2',
        payload: {
          version: 2,
          cards: [card1],
        },
      }),
    });

    ctx = getContext(actor);
    expect(ctx.cards.length).toBe(1);
    expect(ctx.cards[0].content.data.front).toBe('Updated Q');
  });

  it('keeps workspace cards when terminal event follows workspace update', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', runId: 'run-1', query: 'hello' });
    const card = {
      id: 'c-1',
      user_id: 'u-1',
      card_id: 'card-1',
      content: { version: 1, model: 'mcq', data: { front: 'Q', back: 'A' } },
      edit_state: { status: 'draft' as const },
      concepts: [],
      meta: { created_at: '', modified_at: '', manual_edits: 0 },
    };

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'WORKSPACE_UPDATED',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: '10',
        payload: { version: 1, cards: [card] },
      }),
    });
    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'WORKFLOW_COMPLETED',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: '11',
        payload: { message: 'done' },
      }),
    });

    const ctx = getContext(actor);
    expect(ctx.status).toBe('completed');
    expect(ctx.cards).toHaveLength(1);
    expect(ctx.cards[0].card_id).toBe('card-1');
  });

  it('cancel transitions to cancelled', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', query: 'hello' });
    expect(getContext(actor).status).toBe('running');

    // CANCEL → exit running stops SSE actor → cleanup emits 'idle' → cascade to cancelled
    actor.send({ type: 'CANCEL' });
    expect(getContext(actor).status).toBe('cancelled');
    expect(getContext(actor).connectionState).toBe('idle');
  });

  it('pause transitions to paused', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', query: 'hello' });

    // PAUSE → exit running stops SSE actor → cleanup emits 'idle' → cascade to paused
    actor.send({ type: 'PAUSE' });
    expect(getContext(actor).status).toBe('paused');
    expect(getContext(actor).connectionState).toBe('idle');
    // pauseCheckpoint 应已保存
    expect(getContext(actor).pauseCheckpoint).not.toBeNull();
  });

  it('resume goes from paused to running', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', query: 'hello' });
    actor.send({ type: 'PAUSE' });
    actor.send({ type: 'SSE_CONNECTION_STATE', state: 'idle' });
    expect(getContext(actor).status).toBe('paused');

    actor.send({ type: 'RESUME' });
    expect(getContext(actor).status).toBe('running');
    expect(getContext(actor).runPhase).toBe('streaming');
  });

  it('defers non-control events while paused and flushes them after resume', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', runId: 'run-1', query: 'hello' });
    actor.send({ type: 'PAUSE' });

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'thread.message.completed',
        workflow_id: 'wf-1',
        event_id: 'msg-paused',
        payload: { content: 'hidden while paused', stream_id: 'msg-paused' },
      }),
    });

    let ctx = getContext(actor);
    expect(ctx.status).toBe('paused');
    expect(ctx.deferredEvents.length).toBe(1);
    expect(ctx.messages.some((message) => message.content === 'hidden while paused')).toBe(false);

    actor.send({ type: 'RESUME' });
    ctx = getContext(actor);
    expect(ctx.status).toBe('running');
    expect(ctx.deferredEvents.length).toBe(0);
    expect(ctx.messages.some((message) => message.content === 'hidden while paused')).toBe(true);
  });

  it('does not advance the stream watermark while paused', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', runId: 'run-1', query: 'hello' });

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'NODE_STARTED',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: '100',
        payload: { message: 'card_scope_planner started', stream_id: 'progress-100' },
      }),
    });
    expect(getContext(actor).lastEventID).toBe(100);

    actor.send({ type: 'PAUSE' });
    expect(getContext(actor).pauseCheckpoint?.lastEventID).toBe(100);

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'NODE_COMPLETED',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: '300',
        payload: { message: 'card_scope_planner completed', stream_id: 'progress-300' },
      }),
    });

    let ctx = getContext(actor);
    expect(ctx.status).toBe('paused');
    expect(ctx.lastEventID).toBe(100);
    expect(ctx.deferredEvents).toHaveLength(1);
    expect(ctx.messages.some((message) => message.content === 'card_scope_planner completed')).toBe(false);

    actor.send({ type: 'RESUME' });
    ctx = getContext(actor);
    expect(ctx.status).toBe('running');
    expect(ctx.lastEventID).toBe(300);
    expect(ctx.messages.some((message) => message.content === 'card_scope_planner completed')).toBe(true);
  });

  it('advances past deferred progress on resume so later progress can replace it', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', runId: 'run-1', query: 'hello' });
    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'NODE_STARTED',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: '100',
        payload: { message: 'card_scope_planner started', stream_id: 'progress-100' },
      }),
    });

    actor.send({ type: 'PAUSE' });
    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'NODE_COMPLETED',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: '300',
        payload: { message: 'card_scope_planner completed', stream_id: 'progress-300' },
      }),
    });

    actor.send({ type: 'RESUME' });
    let ctx = getContext(actor);
    expect(ctx.lastEventID).toBe(300);
    expect(ctx.messages.find((message) => message.role === 'status')?.content).toBe('card_scope_planner completed');

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'NODE_STARTED',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: '301',
        payload: { message: 'evidence_builder started', stream_id: 'progress-301' },
      }),
    });

    ctx = getContext(actor);
    expect(ctx.lastEventID).toBe(301);
    expect(ctx.messages.find((message) => message.role === 'status')?.content).toBe('evidence_builder started');
  });

  it('keeps workflow.paused timeline records from driving control state after resume', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', runId: 'run-1', query: 'hello' });
    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'NODE_STARTED',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: '101',
        payload: { message: 'card_scope_planner started', stream_id: 'progress-101' },
      }),
    });

    actor.send({ type: 'PAUSE' });
    actor.send({ type: 'RESUME' });
    expect(getContext(actor).status).toBe('running');

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'workflow.paused',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: '102',
        occurred_at: '2026-01-01T00:00:00.000Z',
        payload: {},
      }),
    });

    const ctx = getContext(actor);
    expect(ctx.status).toBe('running');
    expect(ctx.lastEventID).toBe(102);
    expect(ctx.messages.some((message) => message.role === 'status' && message.content === 'Paused')).toBe(false);
  });

  it('keeps control timeline records out of the conversation progress slot after resume', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', runId: 'run-1', query: 'hello' });
    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'NODE_STARTED',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: '110',
        payload: { message: 'card_scope_planner started', stream_id: 'progress-110' },
      }),
    });

    actor.send({ type: 'PAUSE' });
    actor.send({ type: 'RESUME' });

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'NODE_STARTED',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: '111',
        payload: { message: 'card_scope_planner started', stream_id: 'progress-111' },
      }),
    });
    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'workflow.paused',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: '112',
        payload: {},
      }),
    });

    let ctx = getContext(actor);
    expect(ctx.status).toBe('running');
    expect(ctx.messages.some((message) => message.role === 'status' && message.content === 'Paused')).toBe(false);

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'workflow.resumed',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: '113',
        payload: {},
      }),
    });

    ctx = getContext(actor);
    expect(ctx.status).toBe('running');
    expect(ctx.lastEventID).toBe(113);
  });

  it('keeps LLM usage telemetry from replacing visible progress after a resumed node start', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', runId: 'run-1', query: 'hello' });
    actor.send({ type: 'PAUSE' });
    actor.send({ type: 'RESUME' });

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'NODE_STARTED',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: '200',
        payload: { message: 'card_scope_planner started', stream_id: 'progress-200', node_name: 'card_scope_planner' },
      }),
    });
    expect(getContext(actor).messages.find((message) => message.role === 'status')?.content).toBe('card_scope_planner started');

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'LLM_USAGE_RECORDED',
        workflow_id: 'wf-1',
        run_id: 'run-1',
        event_id: '201',
        payload: {
          usage: {
            model: 'gpt-test',
            total_tokens: 42,
          },
        },
      }),
    });

    const ctx = getContext(actor);
    expect(ctx.lastEventID).toBe(201);
    expect(ctx.messages.find((message) => message.role === 'status')?.content).toBe('card_scope_planner started');
  });

  it('does not let stale paused hydration override a local resume intent', () => {
    const actor = createTestActor();
    actor.send({
      type: 'HYDRATE',
      workflowId: 'wf-1',
      runId: 'run-1',
      messages: [{ id: 'user-1', role: 'user', content: 'hello' }],
      events: [
        { id: 100, type: 'NODE_STARTED', workflow_id: 'wf-1', run_id: 'run-1', stream_id: 'e-100', message: 'card_scope_planner started' },
        { id: 101, type: 'workflow.paused', workflow_id: 'wf-1', run_id: 'run-1', stream_id: 'e-101', message: 'Paused' },
      ],
      cards: [],
      state: { active_task_id: 'wf-1', task_state: 'PAUSED', session_control_state: 'ACTIVE_PAUSED' },
    });

    actor.send({ type: 'RESUME' });
    actor.send({
      type: 'HYDRATE',
      workflowId: 'wf-1',
      runId: 'run-1',
      messages: [{ id: 'user-1', role: 'user', content: 'hello' }],
      events: [
        { id: 100, type: 'NODE_STARTED', workflow_id: 'wf-1', run_id: 'run-1', stream_id: 'e-100', message: 'card_scope_planner started' },
        { id: 101, type: 'workflow.paused', workflow_id: 'wf-1', run_id: 'run-1', stream_id: 'e-101', message: 'Paused' },
      ],
      cards: [],
      state: { active_task_id: 'wf-1', task_state: 'PAUSED', session_control_state: 'ACTIVE_PAUSED' },
    });

    const ctx = getContext(actor);
    expect(ctx.status).toBe('running');
    expect(ctx.messages.some((message) => message.role === 'status' && message.content === 'Paused')).toBe(false);
  });

  it('hydrates paused sessions only through the pause checkpoint', () => {
    const actor = createTestActor();
    actor.send({
      type: 'HYDRATE',
      workflowId: 'wf-1',
      runId: 'run-1',
      messages: [{ id: 'user-1', role: 'user', content: 'hello' }],
      events: [
        { id: 1, type: 'NODE_STARTED', workflow_id: 'wf-1', run_id: 'run-1', stream_id: 'e-1', message: 'started' },
        { id: 2, type: 'workflow.paused', workflow_id: 'wf-1', run_id: 'run-1', stream_id: 'e-2', message: 'paused' },
        { id: 3, type: 'NODE_COMPLETED', workflow_id: 'wf-1', run_id: 'run-1', stream_id: 'e-3', message: 'should stay hidden' },
      ],
      cards: [],
      state: { active_task_id: 'wf-1', task_state: 'PAUSED', session_control_state: 'ACTIVE_PAUSED' },
    });

    const ctx = getContext(actor);
    expect(ctx.status).toBe('paused');
    expect(ctx.lastEventID).toBe(2);
    expect(ctx.events.map((event) => event.id)).toEqual([1, 2]);
    expect(ctx.messages.some((message) => message.isGenerating)).toBe(false);
  });

  it('cancel from paused state works', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', query: 'hello' });
    actor.send({ type: 'PAUSE' });
    actor.send({ type: 'SSE_CONNECTION_STATE', state: 'idle' });
    expect(getContext(actor).status).toBe('paused');

    actor.send({ type: 'CANCEL' });
    expect(getContext(actor).status).toBe('cancelled');
  });

  it('SET_MESSAGES restores messages from hydration', () => {
    const actor = createTestActor();
    const existing = [
      { id: 'm-1', role: 'user' as const, content: 'Hi' },
      { id: 'm-2', role: 'assistant' as const, content: 'Hello!' },
    ];
    actor.send({ type: 'SET_MESSAGES', messages: existing });

    const ctx = getContext(actor);
    expect(ctx.messages.length).toBe(2);
    expect(ctx.messages[0].id).toBe('m-1');

    // 新任务应该在会话历史后追加用户消息和 assistant 加载占位
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', query: 'another question' });
    expect(getContext(actor).messages.length).toBe(4);
    expect(getContext(actor).messages.at(-1)?.isGenerating).toBe(true);
  });

  it('local pause clears assistant loading state', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', query: 'hello' });

    actor.send({ type: 'PAUSE' });

    const ctx = getContext(actor);
    expect(ctx.status).toBe('paused');
    expect(ctx.messages.every(m => !m.isGenerating)).toBe(true);
  });

  it('control.cancel.confirmed clears isGenerating and isStreaming', () => {
    const actor = createTestActor();
    actor.send({ type: 'START_WORKFLOW', workflowId: 'wf-1', query: 'hello' });

    actor.send({
      type: 'SSE_ENVELOPE',
      envelope: makeEnvelope({
        event_type: 'workflow.cancelled',
        workflow_id: 'wf-1',
        event_id: 'cancel-1',
        payload: {},
      }),
    });

    const ctx = getContext(actor);
    expect(ctx.status).toBe('cancelled');
    expect(ctx.messages.every(m => !m.isGenerating && !m.isStreaming)).toBe(true);
  });
});
