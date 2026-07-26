/**
 * 新架构的 React Hooks - 使用 React Context 管理 actor
 */

import { useSelector } from '@xstate/react';
import React, { createContext, use, useMemo } from 'react';
import { createActor } from 'xstate';
import { createSessionRegistryMachine } from './session-registry-machine';
import type { RunEvent } from '@/lib/kardcraft/types';
import type { AgentType, CardData, ResearchStrategy, RunMessage, TemplatePreflightState } from './types';

// 创建 Context
const RegistryActorContext = createContext<ReturnType<typeof createActor<ReturnType<typeof createSessionRegistryMachine>>> | null>(null);

/**
 * Provider 组件
 */
export const RunSystemProvider = ({ children }: { children: React.ReactNode }) => {
  const actor = useMemo(() => {
    console.log('[System] Creating registry actor');
    const a = createActor(createSessionRegistryMachine());
    a.start();
    return a;
  }, []);
  
  return (
    <RegistryActorContext.Provider value={actor}>
      {children}
    </RegistryActorContext.Provider>
  );
};

/**
 * 获取 registry actor
 */
export const useRegistryActor = () => {
  const actor = use(RegistryActorContext);
  if (!actor) {
    throw new Error('useRegistryActor must be used within RunSystemProvider');
  }
  return actor;
};

/**
 * 获取会话视图模型
 */
export const useSessionViewModel = (sessionId: string | null) => {
  const registryActor = useRegistryActor();

  // Step 1: Get the session actor ref from the registry (re-evaluates only when sessions map changes)
  const sessionActor = useSelector(
    registryActor,
    (state) => {
      if (!sessionId) return undefined;
      return state.context.sessions[sessionId];
    },
    (a, b) => a === b
  );

  // Debug: trace session resolution
  console.log('[useSessionViewModel]', {
    sessionId,
    hasActor: !!sessionActor,
    registrySessions: Object.keys(registryActor.getSnapshot().context.sessions),
  });

  // Step 2: Subscribe to the session actor directly (re-evaluates on every session state change)
  // This is the key fix — the old code read session snapshot inside the registry's useSelector,
  // which never re-evaluated because the registry doesn't emit when child sessions change.
  const sessionData = useSelector(
    sessionActor,
    (snapshot) => {
      if (!snapshot || !snapshot.context) return null;
      return snapshot.context;
    },
    (a, b) => {
      if (a === b) return true;
      if (!a || !b) return false;
      return (
        a.sessionId === b.sessionId &&
        a.workflowId === b.workflowId &&
        a.runId === b.runId &&
        a.status === b.status &&
        a.runPhase === b.runPhase &&
        a.connectionState === b.connectionState &&
        a.streamError === b.streamError &&
        a.events === b.events &&
        a.messages === b.messages &&
        a.interrupt === b.interrupt &&
        a.cards === b.cards
      );
    }
  );
  
  if (!sessionData) {
    return {
      sessionId: null,
      workflowId: null,
      runId: null,
      status: 'idle' as const,
      runPhase: 'idle' as const,
      connectionState: 'idle' as const,
      streamError: null,
      events: [],
      messages: [],
      cards: [],
      pauseCheckpoint: null,
      isPaused: false,
      isCancelling: false,
      isCancelled: false,
      templatePreflight: {
        status: 'idle' as const,
        templateId: null,
        templateVersion: null,
        questionTypes: [],
        cardCount: null,
        checkedAt: null,
        message: null,
      },
      interrupt: null,
    };
  }
  
  return {
    sessionId: sessionData.sessionId,
    workflowId: sessionData.workflowId,
    runId: sessionData.runId,
    status: sessionData.status,
    runPhase: sessionData.runPhase,
    connectionState: sessionData.connectionState,
    streamError: sessionData.streamError,
    events: sessionData.events,
    messages: sessionData.messages,
    cards: sessionData.cards,
    pauseCheckpoint: sessionData.pauseCheckpoint,
    isPaused: sessionData.status === 'paused',
    isCancelling: sessionData.status === 'cancelling',
    isCancelled: sessionData.status === 'cancelled',
    templatePreflight: sessionData.templatePreflight,
    interrupt: sessionData.interrupt,
  };
};

/**
 * 兼容旧代码：useRunSession
 * 返回简化的会话状态
 */
export const useRunSession = (sessionId: string | null) => {
  const view = useSessionViewModel(sessionId);
  return {
    sessionKey: sessionId || 'new',
    sessionId: view.sessionId,
    lifecycle: 'active' as const,
    cards: view.cards,
    cardsVersion: 0,
    sessionTitle: null,
    activeRunId: view.runId,
    runInstances: {},
    runIdByWorkflowId: {},
    templatePreflight: view.templatePreflight,
  };
};

/**
 * 获取当前活动会话的视图模型
 */
export const useActiveRunSession = () => {
  const registry = useRegistryViewModel();
  const activeSessionId = registry.activeSessionId;
  return useSessionViewModel(activeSessionId);
};

/**
 * 获取注册表视图模型
 */
export const useRegistryViewModel = () => {
  const actor = useRegistryActor();
  
  const selectedAgent = useSelector(actor, (state) => state.context.selectedAgent);
  const researchStrategy = useSelector(actor, (state) => state.context.researchStrategy);
  const activeSessionId = useSelector(actor, (state) => state.context.activeSessionId);
  
  // 获取所有会话的摘要信息，使用比较函数避免不必要的重渲染
  const sessions = useSelector(
    actor,
    (state) => {
      return Object.entries(state.context.sessions)
        .map(([sessionId, sessionActor]) => {
          try {
            const snapshot = sessionActor.getSnapshot();
            const context = snapshot?.context;
            
            if (!context) {
              return null;
            }
            
            return {
              sessionKey: sessionId,
              sessionId: context.sessionId,
              status: context.status,
              runPhase: context.runPhase,
              connectionState: context.connectionState,
              sessionTitle: null,
              mainWorkflowId: context.workflowId,
              mainRunId: context.runId,
            };
          } catch {
            return null;
          }
        })
        .filter((session): session is NonNullable<typeof session> => session !== null);
    },
    (a, b) => {
      // 比较数组长度和每个元素的关键字段
      if (a.length !== b.length) return false;
      for (let i = 0; i < a.length; i++) {
        if (
          a[i].sessionKey !== b[i].sessionKey ||
          a[i].status !== b[i].status ||
          a[i].runPhase !== b[i].runPhase ||
          a[i].connectionState !== b[i].connectionState ||
          a[i].mainWorkflowId !== b[i].mainWorkflowId ||
          a[i].mainRunId !== b[i].mainRunId
        ) {
          return false;
        }
      }
      return true;
    }
  );
  
  return {
    selectedAgent,
    researchStrategy,
    activeSessionId,
    activeSessionKey: activeSessionId || 'new',
    sessionKeys: Object.keys(actor.getSnapshot().context.sessions),
    sessions,
  };
};

/**
 * 获取运行命令
 */
export const useRunCommands = () => {
  const actor = useRegistryActor();
  
  return useMemo(() => ({
    activateSession: (sessionId: string | null) => {
      if (!sessionId) return;
      actor.send({ type: 'ACTIVATE_SESSION', sessionId });
    },
    
    createTask: (sessionId: string | null, workflowId: string, query: string, runId?: string, cursor?: number, userMessage?: RunMessage) => {
      if (!sessionId) return;
      
      // 先激活会话（如果不存在会创建）
      actor.send({ type: 'ACTIVATE_SESSION', sessionId });
      
      // 然后创建任务
      actor.send({ 
        type: 'CREATE_TASK', 
        sessionId, 
        workflowId, 
        runId,
        query,
        cursor,
        userMessage,
      });
    },
    
    pauseSession: (sessionId: string | null) => {
      if (!sessionId) return;
      actor.send({ type: 'PAUSE_SESSION', sessionId });
    },
    
    resumeSession: (sessionId: string | null) => {
      if (!sessionId) return;
      actor.send({ type: 'RESUME_SESSION', sessionId });
    },
    
    cancelSession: (sessionId: string | null) => {
      if (!sessionId) return;
      actor.send({ type: 'CANCEL_SESSION', sessionId });
    },
    
    setSelectedAgent: (value: AgentType) => {
      actor.send({ type: 'SET_SELECTED_AGENT', value });
    },
    
    setResearchStrategy: (value: ResearchStrategy) => {
      actor.send({ type: 'SET_RESEARCH_STRATEGY', value });
    },
    
    addMessage: (sessionId: string, message: RunMessage) => {
      actor.send({ type: 'ADD_MESSAGE', sessionId, message });
    },
    
    upsertCards: (sessionId: string, cards: CardData[]) => {
      actor.send({ type: 'UPSERT_CARDS', sessionId, cards });
    },
    
    // 用于页面刷新后恢复状态
    hydrateSession: (sessionId: string, data: {
      workflowId: string | null;
      runId: string | null;
      messages: RunMessage[];
      events: RunEvent[];
      cards: CardData[];
      cursor?: number;
      interrupt?: import('./session-machine').ConversationInterrupt | null;
      state?: {
        active_task_id?: string | null;
        task_state?: string | null;
        session_control_state?: string | null;
        conversation_status?: import('./types').RunStatus | null;
      } | null;
    }) => {
      actor.send({
        type: 'HYDRATE_SESSION',
        sessionId,
        workflowId: data.workflowId,
        runId: data.runId,
        messages: data.messages,
        events: data.events,
        cards: data.cards,
        cursor: data.cursor,
        interrupt: data.interrupt,
        state: data.state,
      });
    },

    rejectControl: (sessionId: string | null, action: 'pause' | 'resume' | 'cancel', message: string, code?: string | null) => {
      if (!sessionId) return;
      actor.send({
        type: 'CONTROL_REJECTED',
        sessionId,
        action,
        message,
        code,
      });
    },
    
    setTemplatePreflight: (sessionId: string | null, preflight: TemplatePreflightState) => {
      if (!sessionId) return;
      actor.send({
        type: 'SET_TEMPLATE_PREFLIGHT',
        sessionId,
        preflight,
      });
    },
    
    clearTemplatePreflight: (sessionId: string | null) => {
      if (!sessionId) return;
      actor.send({
        type: 'SET_TEMPLATE_PREFLIGHT',
        sessionId,
        preflight: {
          status: 'idle',
          templateId: null,
          templateVersion: null,
          questionTypes: [],
          cardCount: null,
          checkedAt: null,
          message: null,
        },
      });
    },
    
    // 卡片操作（这些操作通过 API 调用后，SSE 会推送更新的卡片）
    bulkUpdateStatus: (_sessionId: string | null, _cardIds: string[], _status: string) => {
      void _sessionId;
      void _cardIds;
      void _status;
      // 卡片状态更新通过 API 完成，SSE 会推送更新
      console.log('[bulkUpdateStatus] Card updates handled by API + SSE');
    },
    
    updateCardQuestionType: (_sessionId: string | null, _cardId: string, _questionType: string) => {
      void _sessionId;
      void _cardId;
      void _questionType;
      // 卡片更新通过 API 完成，SSE 会推送更新
      console.log('[updateCardQuestionType] Card updates handled by API + SSE');
    },
    
    updateCardStatus: (_sessionId: string | null, _cardId: string, _status: string) => {
      void _sessionId;
      void _cardId;
      void _status;
      // 卡片状态更新通过 API 完成，SSE 会推送更新
      console.log('[updateCardStatus] Card updates handled by API + SSE');
    },
  }), [actor]);
};
