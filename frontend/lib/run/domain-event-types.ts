import type { CardData } from "./types";

export type ControlErrorCode =
    | "INVALID_TRANSITION"
    | "TASK_NOT_FOUND"
    | "SESSION_MISMATCH"
    | "AUTHZ_DENIED"
    | "CONFLICT"
    | "TIMEOUT"
    | "TRANSPORT_UNAVAILABLE"
    | "INTERNAL";

export type RunDomainEvent =
    (
    | {
          kind: "task.created";
          taskId: string;
          sessionId: string;
          query: string;
          createdAt: string;
      }
    | {
          kind: "workflow.started";
          workflowId: string;
          sessionId: string | null;
          at: string;
      }
    | {
          kind: "workflow.completed";
          workflowId: string;
          sessionId: string | null;
          at: string;
          result?: unknown;
      }
    | {
          kind: "workflow.failed";
          workflowId: string;
          sessionId: string | null;
          at: string;
          reasonCode: string;
          message: string;
      }
    | {
          kind: "run.finished";
          workflowId: string;
          outcome: "normal" | "interrupt" | "cancelled";
          interrupt?: {
              interrupt_id: string;
              type: string;
              prompt: string;
              input_schema?: Record<string, unknown>;
              metadata?: Record<string, unknown>;
          };
          at: string;
      }
    | {
          kind: "message.started";
          workflowId: string;
          messageId: string;
          role: "assistant";
          at: string;
      }
    | {
          kind: "message.delta";
          workflowId: string;
          messageId: string;
          delta: string;
          seq?: number;
          at: string;
      }
    | {
          kind: "message.completed";
          workflowId: string;
          messageId: string;
          content: string;
          metadata?: Record<string, unknown>;
          at: string;
      }
    | {
          kind: "timeline.event";
          workflowId: string;
          eventId: string;
          eventKind: string;
          streamId?: string;
          payload?: unknown;
          at: string;
          message?: string;
          agentId?: string;
          seq?: number;
      }
    | {
          kind: "workspace.updated";
          sessionId: string;
          version: number;
          cards: CardData[];
          at: string;
      }
    | {
          kind: "control.cancel.confirmed";
          taskId: string;
          sessionId: string | null;
          at: string;
      }
    | {
          kind: "control.rejected";
          taskId: string;
          sessionId: string | null;
          code: ControlErrorCode;
          message: string;
          at: string;
      }) & {
          runId?: string | null;
      };

export type DomainEventRejectReason =
    | "invalid_payload"
    | "missing_workflow_id"
    | "unsupported_empty_message";

export type DomainEventMapResult =
    | { ok: true; event: RunDomainEvent }
    | { ok: false; reason: DomainEventRejectReason; details?: string };
