/**
 * 每会话独立的 SSE Actor
 * 
 * 核心理念：
 * - 每个会话有自己的 SSE 连接
 * - 独立管理 lastEventID
 * - 暂停 = 关闭连接 + 保存 checkpoint
 * - 继续 = 用 checkpoint 重新连接
 */

import { fetchEventSource } from '@microsoft/fetch-event-source';
import { fromCallback } from 'xstate';
import { getStreamUrlForWorkflows } from '@/lib/kardcraft/api';
import type { RuntimeEnvelope } from './runtime-envelope';
import { validateRuntimeEnvelope } from './runtime-envelope';
import type { ConnectionState } from './types';

export const SESSION_SSE_WATCHDOG_INTERVAL_MS = 5_000;
export const SESSION_SSE_STALE_CONNECTION_MS = 30_000;

export type SessionSseInputEvent =
  | { type: 'CONNECT'; lastEventID?: number; includeLastEventID?: boolean }
  | { type: 'PAUSE' }
  | { type: 'RESUME' }
  | { type: 'DISCONNECT' };

export type SessionSseOutputEvent =
  | { type: 'SSE_CONNECTION_STATE'; state: ConnectionState }
  | { type: 'SSE_ERROR'; message: string }
  | { type: 'SSE_ENVELOPE'; envelope: RuntimeEnvelope };

export type SessionSseConfig = {
  workflowId: string;
  sessionId: string;
  lastEventID?: number;
  includeLastEventID?: boolean;
};

class FatalError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'FatalError';
  }
}

export function createSessionSseActor() {
  return fromCallback<SessionSseInputEvent, SessionSseConfig, SessionSseOutputEvent>(({ sendBack, receive, input }) => {
    const config = input ?? { workflowId: '', sessionId: '' };
    const { workflowId } = config;
    
    let abortController: AbortController | null = null;
    let lastEventID = config.lastEventID || 0;
    let pauseCheckpoint: number | null = null;
    let isConnecting = false;
    let connectionGeneration = 0;
    let watchdogTimer: ReturnType<typeof setInterval> | null = null;
    let lastActivityAt = 0;

    const log = (message: string, ...args: unknown[]) => {
      console.log(`[SessionSSE:${workflowId.slice(-8)}] ${message}`, ...args);
    };

    const emitState = (state: ConnectionState) => {
      sendBack({ type: 'SSE_CONNECTION_STATE', state });
    };

    const emitError = (message: string) => {
      sendBack({ type: 'SSE_ERROR', message });
    };

    const clearWatchdog = () => {
      if (watchdogTimer) {
        clearInterval(watchdogTimer);
        watchdogTimer = null;
      }
    };

    const startWatchdog = (generation: number) => {
      clearWatchdog();
      watchdogTimer = setInterval(() => {
        if (generation !== connectionGeneration) return;
        if (!abortController || abortController.signal.aborted) return;

        const idleMs = Date.now() - lastActivityAt;
        if (idleMs < SESSION_SSE_STALE_CONNECTION_MS) return;

        log(`Watchdog reconnect after ${idleMs}ms idle, lastEventID=${lastEventID}`);
        emitState('reconnecting');
        connect(lastEventID, true);
      }, SESSION_SSE_WATCHDOG_INTERVAL_MS);
    };

    const stopCurrentConnection = () => {
      connectionGeneration += 1;
      clearWatchdog();
      // 关闭旧连接
      if (abortController) {
        log('Aborting existing connection');
        abortController.abort();
        abortController = null;
      }
      isConnecting = false;
    };

    const connect = (startFromEventID?: number, includeLastEventID?: boolean) => {
      stopCurrentConnection();
      const generation = connectionGeneration;

      const eventID = startFromEventID ?? lastEventID;
      log(`Connecting with lastEventID=${eventID}`);

      abortController = new AbortController();
      isConnecting = true;
      lastActivityAt = Date.now();
      startWatchdog(generation);
      emitState('connecting');

      const url = getStreamUrlForWorkflows([workflowId], {
        lastEventID: eventID,
        includeLastEventID,
      });
      log('Connecting to URL:', url);

      fetchEventSource(url, {
        signal: abortController.signal,
        credentials: 'include',

        async onopen(response) {
          if (generation !== connectionGeneration) {
            return;
          }
          isConnecting = false;
          lastActivityAt = Date.now();

          if (response.ok) {
            log('Connected successfully');
            emitState('connected');
          } else {
            const body = await response.text().catch(() => '');
            log(`Connection failed: status=${response.status} body=${body}`);
            if (response.status >= 400 && response.status < 500 && response.status !== 429) {
              emitError(`Connection failed: ${response.status} ${body.slice(0, 200)}`);
              throw new FatalError(`HTTP ${response.status}`);
            } else {
              throw new Error(`HTTP ${response.status}`);
            }
          }
        },

        onmessage(event) {
          if (generation !== connectionGeneration) {
            return;
          }
          lastActivityAt = Date.now();
          // 更新 lastEventID
          if (event.id) {
            const eventID = Number(event.id);
            if (Number.isFinite(eventID) && eventID > 0) {
              lastEventID = Math.max(lastEventID, Math.floor(eventID));
            }
          }

          // 跳过空事件
          if (!event.data || event.data === '[DONE]' || event.data === 'undefined') {
            return;
          }

          log('Received event:', { type: event.event || 'message', id: event.id, dataPreview: event.data.slice(0, 80) });

          // 解析并验证事件
          try {
            const parsed = JSON.parse(event.data);
            const validated = validateRuntimeEnvelope(parsed);

            if (!validated.ok) {
              log(`Invalid envelope: ${validated.reason}`, { dataPreview: event.data.slice(0, 120) });
              return;
            }

            const envelope = validated.value;

            // 使用 SSE 的 event type 如果有的话
            if (event.event && event.event !== 'message') {
              envelope.event_type = event.event;
            }

            // 确保 event_id 存在
            if (event.id && !envelope.event_id) {
              envelope.event_id = event.id;
            }

            log('Sending SSE_ENVELOPE to session:', { event_type: envelope.event_type, workflow_id: envelope.workflow_id });
            sendBack({ type: 'SSE_ENVELOPE', envelope });
          } catch (error) {
            log('Failed to parse event:', error);
          }
        },

        onerror(error) {
          if (generation !== connectionGeneration) {
            throw error;
          }
          isConnecting = false;

          if (error instanceof FatalError) {
            log('Fatal error, stopping reconnection');
            emitState('error');
            throw error; // 停止重连
          }

          log('Connection error:', error);
          emitState('reconnecting');

          return 1000;
        },

        onclose() {
          if (generation !== connectionGeneration) {
            return;
          }
          isConnecting = false;

          log('Connection closed by server, reconnecting');
          emitState('reconnecting');
          throw new Error('SSE connection closed before terminal event');
        },

        openWhenHidden: true, // 后台标签页也保持连接
      }).catch((error) => {
        if (generation !== connectionGeneration) {
          return;
        }
        clearWatchdog();
        isConnecting = false;

        if (error instanceof FatalError) {
          log('Fatal error caught, connection stopped');
          emitState('idle'); // 致命错误后连接状态为 idle
        } else {
          log('Connection closed:', error);
        }
      });
    };

    const pause = () => {
      log(`Pausing, saving checkpoint=${lastEventID}`);
      
      pauseCheckpoint = lastEventID;
      stopCurrentConnection();
      emitState('idle'); // 暂停后连接状态为 idle
    };

    const resume = () => {
      const resumeFrom = pauseCheckpoint ?? lastEventID;
      log(`Resuming from eventID=${resumeFrom}`);
      
      connect(resumeFrom, true);
      pauseCheckpoint = null;
    };

    const disconnect = () => {
      log('Disconnecting');
      stopCurrentConnection();
      pauseCheckpoint = null;
      emitState('idle'); // 断开后连接状态为 idle
    };

    // 处理命令
    receive((event) => {
      if (event.type === 'CONNECT') {
        connect(event.lastEventID, event.includeLastEventID);
      } else if (event.type === 'PAUSE') {
        pause();
      } else if (event.type === 'RESUME') {
        resume();
      } else if (event.type === 'DISCONNECT') {
        disconnect();
      }
    });

    // 清理函数
    return () => {
      log('Actor cleanup');
      disconnect();
    };
  });
}
