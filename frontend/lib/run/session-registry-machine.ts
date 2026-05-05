/**
 * 会话注册表状态机 (V2 - 简化版本)
 * 
 * 管理多个会话，每个会话有独立的 SSE 连接
 */

import { assign, createMachine, type ActorRefFrom } from 'xstate';
import type { SessionContext } from './session-machine';
import { createSessionMachine } from './session-machine';
import type { RunEvent } from '@/lib/kardcraft/types';
import type { AgentType, CardData, ResearchStrategy, RunMessage, TemplatePreflightState } from './types';

export type SessionRegistryContext = {
  // 会话管理
  sessions: Record<string, ActorRefFrom<ReturnType<typeof createSessionMachine>>>;
  activeSessionId: string | null;
  
  // 全局设置
  selectedAgent: AgentType;
  researchStrategy: ResearchStrategy;
};

export type SessionRegistryEvent =
  | { type: 'ACTIVATE_SESSION'; sessionId: string }
  | { type: 'CREATE_TASK'; sessionId: string; workflowId: string; runId?: string; query: string }
  | {
      type: 'HYDRATE_SESSION';
      sessionId: string;
      workflowId: string | null;
      runId: string | null;
      messages: RunMessage[];
      events: RunEvent[];
      cards: CardData[];
      state?: {
        active_task_id?: string | null;
        task_state?: string | null;
        session_control_state?: string | null;
      } | null;
    }
  | { type: 'PAUSE_SESSION'; sessionId: string }
  | { type: 'RESUME_SESSION'; sessionId: string }
  | { type: 'CANCEL_SESSION'; sessionId: string }
  | { type: 'CONTROL_REJECTED'; sessionId: string; action: 'pause' | 'resume' | 'cancel'; message: string; code?: string | null }
  | { type: 'SET_SELECTED_AGENT'; value: AgentType }
  | { type: 'SET_RESEARCH_STRATEGY'; value: ResearchStrategy }
  | { type: 'ADD_MESSAGE'; sessionId: string; message: RunMessage }
  | { type: 'UPSERT_CARDS'; sessionId: string; cards: CardData[] }
  | { type: 'SET_TEMPLATE_PREFLIGHT'; sessionId: string; preflight: TemplatePreflightState };

export const createSessionRegistryMachine = () => {
  return createMachine({
    id: 'sessionRegistry',
    
    context: {
      sessions: {},
      activeSessionId: null,
      selectedAgent: 'normal' as AgentType,
      researchStrategy: 'quick' as ResearchStrategy,
    } as SessionRegistryContext,
    
    types: {
      context: {} as SessionRegistryContext,
      events: {} as SessionRegistryEvent,
    },
    
    initial: 'active',
    
    states: {
      active: {
        on: {
          ACTIVATE_SESSION: {
            actions: assign({
              sessions: ({ context, event, spawn }) => {
                const sessionId = event.sessionId;
                
                // 如果会话不存在，创建新的
                if (!context.sessions[sessionId]) {
                  console.log('[Registry] Creating session:', sessionId);
                  // XState v5: spawn(logic, options)
                  const sessionActor = spawn(createSessionMachine(sessionId), {
                    id: `session-${sessionId}`,
                    input: sessionId,
                  });
                  
                  return {
                    ...context.sessions,
                    [sessionId]: sessionActor,
                  };
                }
                
                return context.sessions;
              },
              activeSessionId: ({ event }) => event.sessionId,
            }),
          },
          
          CREATE_TASK: {
            actions: [
              // 先确保会话存在
              assign({
                sessions: ({ context, event, spawn }) => {
                  const sessionId = event.sessionId;
                  
                  if (!context.sessions[sessionId]) {
                    console.log('[Registry] CREATE_TASK: Creating session:', sessionId);
                    const sessionActor = spawn(createSessionMachine(sessionId), {
                      id: `session-${sessionId}`,
                      input: sessionId,
                    });
                    
                    return {
                      ...context.sessions,
                      [sessionId]: sessionActor,
                    };
                  }
                  
                  return context.sessions;
                },
                activeSessionId: ({ event }) => event.sessionId,
              }),
              // 然后启动工作流
              ({ context, event }) => {
                const session = context.sessions[event.sessionId];
                if (session) {
                  console.log('[Registry] Starting workflow:', event.workflowId);
                  session.send({
                    type: 'START_WORKFLOW',
                    workflowId: event.workflowId,
                    runId: event.runId || event.workflowId,
                    query: event.query,
                  });
                }
              },
            ],
          },
          
          HYDRATE_SESSION: {
            actions: [
              // 创建会话
              assign({
                sessions: ({ context, event, spawn }) => {
                  const sessionId = event.sessionId;
                  
                  if (!context.sessions[sessionId]) {
                    console.log('[Registry] HYDRATE: Creating session:', sessionId);
                    const sessionActor = spawn(createSessionMachine(sessionId), {
                      id: `session-${sessionId}`,
                      input: sessionId,
                    });
                    
                    return {
                      ...context.sessions,
                      [sessionId]: sessionActor,
                    };
                  }
                  
                  return context.sessions;
                },
                activeSessionId: ({ event }) => event.sessionId,
              }),
              // 恢复完整运行态，由会话状态机统一裁剪可见进度并推导状态
              ({ context, event }) => {
                const session = context.sessions[event.sessionId];
                if (session) {
                  console.log('[Registry] Hydrating session runtime:', event.sessionId);
                  session.send({
                    type: 'HYDRATE',
                    workflowId: event.workflowId,
                    runId: event.runId,
                    messages: event.messages,
                    events: event.events,
                    cards: event.cards,
                    state: event.state,
                  });
                }
              },
            ],
          },
          
          PAUSE_SESSION: {
            actions: ({ context, event }) => {
              const session = context.sessions[event.sessionId];
              if (session) {
                session.send({ type: 'PAUSE' });
              }
            },
          },
          
          RESUME_SESSION: {
            actions: ({ context, event }) => {
              const session = context.sessions[event.sessionId];
              if (session) {
                session.send({ type: 'RESUME' });
              }
            },
          },
          
          CANCEL_SESSION: {
            actions: ({ context, event }) => {
              const session = context.sessions[event.sessionId];
              if (session) {
                session.send({ type: 'CANCEL' });
              }
            },
          },

          CONTROL_REJECTED: {
            actions: ({ context, event }) => {
              const session = context.sessions[event.sessionId];
              if (session) {
                session.send({
                  type: 'CONTROL_REJECTED',
                  action: event.action,
                  message: event.message,
                  code: event.code,
                });
              }
            },
          },
          
          SET_SELECTED_AGENT: {
            actions: assign({
              selectedAgent: ({ event }) => event.value,
            }),
          },
          
          SET_RESEARCH_STRATEGY: {
            actions: assign({
              researchStrategy: ({ event }) => event.value,
            }),
          },
          
          ADD_MESSAGE: {
            actions: ({ context, event }) => {
              const session = context.sessions[event.sessionId];
              if (session) {
                session.send({
                  type: 'ADD_MESSAGE',
                  message: event.message,
                });
              }
            },
          },
          
          UPSERT_CARDS: {
            actions: ({ context, event }) => {
              const session = context.sessions[event.sessionId];
              if (session) {
                session.send({
                  type: 'UPSERT_CARDS',
                  cards: event.cards,
                });
              }
            },
          },
          
          SET_TEMPLATE_PREFLIGHT: {
            actions: ({ context, event }) => {
              const session = context.sessions[event.sessionId];
              if (session) {
                session.send({
                  type: 'SET_TEMPLATE_PREFLIGHT',
                  preflight: event.preflight,
                });
              }
            },
          },
        },
      },
    },
  });
};

// 辅助函数：从会话 actor 获取快照
export const getSessionSnapshot = (
  sessionActor: ActorRefFrom<ReturnType<typeof createSessionMachine>>
): SessionContext => {
  return sessionActor.getSnapshot().context;
};
