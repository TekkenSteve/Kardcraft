import type { RunEvent } from "@/lib/kardcraft/types";
import { assign, createMachine, sendTo } from "xstate";
import type { RunDomainEvent } from "./domain-event-types";
import { mapControlErrorToDomainEvent, mapWireEventToDomainEvent, projectDomainEventToRunEvent } from "./domain-events";
import type { RuntimeEnvelope } from "./runtime-envelope";
import { createSessionSseActor, type SessionSseConfig } from "./session-sse-actor";
import type { CardData, ConnectionState, RunMessage, RunPhase, RunStatus, TemplatePreflightState } from "./types";

const SSE_ACTOR_ID = "sseActor";
const sseActor = createSessionSseActor();

type HydratedState = {
  active_task_id?: string | null;
  task_state?: string | null;
  session_control_state?: string | null;
};

type LocalControlIntent = {
  action: "pause" | "resume" | "cancel";
  at: string;
  checkpointEventID: number;
};

export type SessionContext = {
  sessionId: string;
  workflowId: string | null;
  runId: string | null;
  status: RunStatus;
  runPhase: RunPhase;
  connectionState: ConnectionState;
  streamError: string | null;
  events: RunEvent[];
  messages: RunMessage[];
  cards: CardData[];
  lastEventID: number;
  pauseCheckpoint: { lastEventID: number; timestamp: string } | null;
  deferredEvents: RunDomainEvent[];
  controlIntent: LocalControlIntent | null;
  templatePreflight: TemplatePreflightState;
};

export type SessionEvent =
  | { type: "START_WORKFLOW"; workflowId: string; runId?: string | null; query?: string }
  | { type: "HYDRATE"; workflowId: string | null; runId: string | null; messages: RunMessage[]; events: RunEvent[]; cards: CardData[]; state?: HydratedState | null }
  | { type: "PAUSE" }
  | { type: "RESUME" }
  | { type: "CANCEL" }
  | { type: "CONTROL_REJECTED"; action: "pause" | "resume" | "cancel"; message: string; code?: string | null }
  | { type: "SSE_CONNECTION_STATE"; state: ConnectionState }
  | { type: "SSE_ERROR"; message: string }
  | { type: "SSE_ENVELOPE"; envelope: RuntimeEnvelope }
  | { type: "ADD_MESSAGE"; message: RunMessage }
  | { type: "SET_MESSAGES"; messages: RunMessage[] }
  | { type: "UPSERT_CARDS"; cards: CardData[] }
  | { type: "SET_TEMPLATE_PREFLIGHT"; preflight: TemplatePreflightState };

const createInitialContext = (sessionId: string): SessionContext => ({
  sessionId,
  workflowId: null,
  runId: null,
  status: "idle",
  runPhase: "idle",
  connectionState: "idle",
  streamError: null,
  events: [],
  messages: [],
  cards: [],
  lastEventID: 0,
  pauseCheckpoint: null,
  deferredEvents: [],
  controlIntent: null,
  templatePreflight: {
    status: "idle",
    templateId: null,
    templateVersion: null,
    questionTypes: [],
    cardCount: null,
    checkedAt: null,
    message: null,
  },
});

const CONTROL_EVENT_KINDS = new Set<RunDomainEvent["kind"]>([
  "control.cancel.confirmed",
  "control.rejected",
]);

const CONTROL_TIMELINE_TYPES = new Set<string>([
  "workflow.pausing",
  "workflow.resuming",
  "workflow.paused",
  "workflow.resumed",
  "workflow.cancelling",
]);

const TELEMETRY_TIMELINE_TYPES = new Set<string>([
  "LLM_USAGE_RECORDED",
]);

const TERMINAL_STATUSES = new Set<RunStatus>(["completed", "failed", "cancelled"]);

const isTerminalStatus = (status: RunStatus) => TERMINAL_STATUSES.has(status);

const shouldReplayBacklogFromCursor = (context: SessionContext): boolean =>
  context.controlIntent?.action === "resume" &&
  context.lastEventID <= context.controlIntent.checkpointEventID;

const extractRunEventID = (event: RunEvent): number => {
  const raw = (event as { id?: unknown }).id;
  if (typeof raw === "number" && Number.isFinite(raw)) return Math.floor(raw);
  if (typeof raw === "string") {
    const parsed = Number(raw);
    if (Number.isFinite(parsed)) return Math.floor(parsed);
  }
  return 0;
};

const extractEnvelopeEventID = (envelope: RuntimeEnvelope): number => {
  const parsed = Number(envelope.event_id);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0;
};

const eventIdentity = (event: RunEvent): string => {
  const streamId = (event as { stream_id?: unknown }).stream_id;
  const workflowId = (event as { workflow_id?: unknown }).workflow_id;
  const runId = (event as { run_id?: unknown }).run_id;
  const id = (event as { id?: unknown }).id;
  return [
    typeof workflowId === "string" ? workflowId : "",
    typeof runId === "string" ? runId : "",
    event.type,
    typeof streamId === "string" && streamId.length > 0 ? streamId : String(id ?? ""),
  ].join("\u0000");
};

const mergeEvents = (current: RunEvent[], incoming: RunEvent[]): RunEvent[] => {
  const seen = new Set(current.map(eventIdentity));
  const next = [...current];
  incoming.forEach((event) => {
    const key = eventIdentity(event);
    if (seen.has(key)) return;
    seen.add(key);
    next.push(event);
  });
  return next;
};

const maxEventID = (events: RunEvent[]): number => events.reduce((max, event) => Math.max(max, extractRunEventID(event)), 0);

const hasPendingAssistant = (messages: RunMessage[], workflowId: string | null): boolean => {
  if (!workflowId) return false;
  return messages.some((message) => message.role === "assistant" && message.taskId === workflowId && (message.isGenerating || message.isStreaming));
};

const hasAssistantReply = (messages: RunMessage[], workflowId: string | null): boolean => {
  if (!workflowId) return false;
  return messages.some((message) => message.role === "assistant" && message.taskId === workflowId && !message.isGenerating && message.content.trim().length > 0);
};

const ensureAssistantPlaceholder = (messages: RunMessage[], workflowId: string | null, at: string = new Date().toISOString()): RunMessage[] => {
  if (!workflowId || hasPendingAssistant(messages, workflowId) || hasAssistantReply(messages, workflowId)) return messages;
  return [
    ...messages,
    {
      id: `generating-${workflowId}`,
      role: "assistant",
      content: "",
      isGenerating: true,
      taskId: workflowId,
      timestamp: at,
    },
  ];
};

const clearAssistantLoading = (messages: RunMessage[]): RunMessage[] =>
  messages.map((message) => ({
    ...message,
    isGenerating: false,
    isStreaming: false,
  }));

const removeEmptyAssistantPlaceholders = (messages: RunMessage[], workflowId: string | null): RunMessage[] =>
  messages.filter((message) => {
    if (message.role !== "assistant") return true;
    if (workflowId && message.taskId !== workflowId) return true;
    if (message.isGenerating || message.isStreaming) return true;
    return message.content.trim().length > 0;
  });

const removeStatusMessages = (messages: RunMessage[], workflowId: string | null): RunMessage[] =>
  messages.filter((message) => message.role !== "status" || (workflowId && message.taskId !== workflowId));

const upsertCards = (current: CardData[], incoming: CardData[]): CardData[] => {
  const byId = new Map(current.map((card) => [card.card_id, card]));
  incoming.forEach((card) => byId.set(card.card_id, card));
  return Array.from(byId.values());
};

const directResultMessage = (result: unknown): string | null => {
  if (!result || typeof result !== "object") return null;
  const record = result as Record<string, unknown>;
  const candidate = record.response ?? record.message ?? record.content;
  return typeof candidate === "string" && candidate.trim().length > 0 ? candidate : null;
};

const applyTerminalAssistantResult = (messages: RunMessage[], workflowId: string, result: unknown, at: string): RunMessage[] => {
  const content = directResultMessage(result);
  if (!content || hasAssistantReply(messages, workflowId)) return messages;
  const existingIndex = messages.findIndex((message) =>
    message.role === "assistant" &&
    message.taskId === workflowId &&
    (message.isGenerating || message.isStreaming || message.content.trim().length === 0)
  );
  if (existingIndex >= 0) {
    const next = [...messages];
    next[existingIndex] = {
      ...next[existingIndex],
      content,
      isGenerating: false,
      isStreaming: false,
      timestamp: next[existingIndex].timestamp || at,
    };
    return next;
  }
  return [
    ...messages,
    {
      id: `assistant-${workflowId}`,
      role: "assistant",
      content,
      taskId: workflowId,
      timestamp: at,
    },
  ];
};

const finalizeTerminalMessages = (messages: RunMessage[], workflowId: string, result: unknown, at: string): RunMessage[] =>
  removeStatusMessages(
    removeEmptyAssistantPlaceholders(clearAssistantLoading(applyTerminalAssistantResult(messages, workflowId, result, at)), workflowId),
    workflowId,
  );

const statusMessageContent = (event: Extract<RunDomainEvent, { kind: "timeline.event" }>): string => {
  const message = event.message?.trim();
  if (message) return message;
  return event.eventKind.replace(/_/g, " ").toLowerCase();
};

const setStatusMessage = (messages: RunMessage[], input: {
  workflowId: string;
  content: string;
  at: string;
  eventType: string;
}): RunMessage[] => {
  const content = input.content.trim();
  if (!content.trim()) return messages;
  const id = `status-${input.workflowId}`;
  return [
    ...removeStatusMessages(messages, input.workflowId),
    {
      id,
      role: "status",
      content,
      timestamp: input.at,
      taskId: input.workflowId,
      eventType: input.eventType,
    },
  ];
};

const upsertStatusMessage = (messages: RunMessage[], event: Extract<RunDomainEvent, { kind: "timeline.event" }>): RunMessage[] =>
  setStatusMessage(messages, {
    workflowId: event.workflowId,
    content: statusMessageContent(event),
    at: event.at,
    eventType: event.eventKind,
  });

const shouldDeferEvent = (context: SessionContext, event: RunDomainEvent): boolean => {
  if (context.status !== "paused" && context.status !== "pausing") return false;
  return !CONTROL_EVENT_KINDS.has(event.kind);
};

const isControlTimelineEvent = (event: RunDomainEvent): boolean =>
  event.kind === "timeline.event" && CONTROL_TIMELINE_TYPES.has(event.eventKind);

const applyDomainEvent = (context: SessionContext, event: RunDomainEvent): Partial<SessionContext> => {
  const projected = projectDomainEventToRunEvent(event);
  const nextEvents = projected ? mergeEvents(context.events, [projected]) : context.events;
  const updates: Partial<SessionContext> = {
    events: nextEvents,
    lastEventID: Math.max(context.lastEventID, projected ? extractRunEventID(projected) : 0),
  };

  switch (event.kind) {
    case "workflow.started":
      updates.status = "running";
      updates.runPhase = "streaming";
      updates.workflowId = event.workflowId;
      updates.runId = event.runId || context.runId;
      updates.streamError = null;
      updates.controlIntent = null;
      updates.messages = ensureAssistantPlaceholder(context.messages, event.workflowId, event.at);
      break;

    case "workflow.completed": {
      updates.status = "completed";
      updates.runPhase = "hydrated";
      updates.connectionState = "idle";
      updates.pauseCheckpoint = null;
      updates.deferredEvents = [];
      updates.controlIntent = null;
      updates.messages = finalizeTerminalMessages(context.messages, event.workflowId, event.result, event.at);
      break;
    }

    case "workflow.failed":
      updates.status = "failed";
      updates.runPhase = "error";
      updates.connectionState = "idle";
      updates.streamError = event.message;
      updates.pauseCheckpoint = null;
      updates.deferredEvents = [];
      updates.controlIntent = null;
      updates.messages = removeStatusMessages(
        removeEmptyAssistantPlaceholders(clearAssistantLoading(context.messages), event.workflowId),
        event.workflowId,
      );
      break;

    case "message.delta": {
      const exactIndex = context.messages.findIndex((message) => message.id === event.messageId);
      if (exactIndex >= 0) {
        const messages = [...context.messages];
        messages[exactIndex] = {
          ...messages[exactIndex],
          content: (messages[exactIndex].content || "") + event.delta,
          isStreaming: true,
          isGenerating: false,
        };
        updates.messages = messages;
        break;
      }

      const generatingIndex = context.messages.findIndex((message) => message.isGenerating && message.taskId === event.workflowId);
      if (generatingIndex >= 0) {
        const messages = [...context.messages];
        messages[generatingIndex] = {
          id: event.messageId,
          role: "assistant",
          content: event.delta,
          isStreaming: true,
          isGenerating: false,
          taskId: event.workflowId,
          timestamp: event.at,
        };
        updates.messages = messages;
        break;
      }

      updates.messages = [
        ...context.messages,
        {
          id: event.messageId,
          role: "assistant",
          content: event.delta,
          isStreaming: true,
          taskId: event.workflowId,
          timestamp: event.at,
        },
      ];
      break;
    }

    case "message.completed": {
      const completedIndex = context.messages.findIndex((message) => message.id === event.messageId);
      if (completedIndex >= 0) {
        const messages = [...context.messages];
        messages[completedIndex] = {
          ...messages[completedIndex],
          content: event.content,
          isStreaming: false,
          isGenerating: false,
          metadata: event.metadata,
        };
        updates.messages = messages;
        break;
      }

      const generatingIndex = context.messages.findIndex((message) => message.isGenerating && message.taskId === event.workflowId);
      if (generatingIndex >= 0) {
        const messages = [...context.messages];
        messages[generatingIndex] = {
          id: event.messageId,
          role: "assistant",
          content: event.content,
          isGenerating: false,
          isStreaming: false,
          taskId: event.workflowId,
          timestamp: event.at,
          metadata: event.metadata,
        };
        updates.messages = messages;
        break;
      }

      updates.messages = [
        ...context.messages,
        {
          id: event.messageId,
          role: "assistant",
          content: event.content,
          taskId: event.workflowId,
          timestamp: event.at,
          metadata: event.metadata,
        },
      ];
      break;
    }

    case "workspace.updated":
      updates.cards = upsertCards(context.cards, event.cards);
      break;

    case "timeline.event":
      if (isControlTimelineEvent(event)) {
        break;
      }
      if (TELEMETRY_TIMELINE_TYPES.has(event.eventKind)) {
        break;
      }
      updates.messages = upsertStatusMessage(context.messages, event);
      break;

    case "control.cancel.confirmed":
      updates.status = "cancelled";
      updates.runPhase = "hydrated";
      updates.connectionState = "idle";
      updates.pauseCheckpoint = null;
      updates.deferredEvents = [];
      updates.controlIntent = null;
      updates.messages = removeStatusMessages(
        removeEmptyAssistantPlaceholders(clearAssistantLoading(context.messages), event.taskId),
        event.taskId,
      );
      break;

    case "control.rejected":
      updates.streamError = event.message;
      break;
  }

  return updates;
};

const envelopeToDomainEvent = (context: SessionContext, envelope: RuntimeEnvelope) => {
  const payload = envelope.run_id ? { ...envelope.payload, run_id: envelope.run_id } : envelope.payload;
  return mapWireEventToDomainEvent({
    eventType: envelope.event_type,
    payload,
    fallbackWorkflowId: envelope.workflow_id,
    fallbackSessionId: envelope.session_id,
    at: envelope.occurred_at,
    eventId: envelope.event_id,
  });
};

const ingestEnvelope = (context: SessionContext, envelope: RuntimeEnvelope): Partial<SessionContext> => {
  const eventID = extractEnvelopeEventID(envelope);
  const mapped = envelopeToDomainEvent(context, envelope);
  if (!mapped.ok) {
    return {
      lastEventID: Math.max(context.lastEventID, eventID),
    };
  }

  if (context.workflowId && "workflowId" in mapped.event && mapped.event.workflowId !== context.workflowId) {
    return {
      lastEventID: Math.max(context.lastEventID, eventID),
    };
  }

  if (shouldDeferEvent(context, mapped.event)) {
    return {
      lastEventID: context.lastEventID,
      deferredEvents: [...context.deferredEvents, mapped.event],
    };
  }

  const updates = applyDomainEvent(context, mapped.event);
  updates.lastEventID = Math.max(context.lastEventID, eventID, updates.lastEventID ?? 0);
  return updates;
};

const applyDeferredEvents = (context: SessionContext): Partial<SessionContext> => {
  if (context.deferredEvents.length === 0) {
    return {
      pauseCheckpoint: null,
      messages: ensureAssistantPlaceholder(context.messages, context.workflowId),
    };
  }

  let next: SessionContext = {
    ...context,
    status: "running",
    runPhase: "streaming",
    pauseCheckpoint: null,
    deferredEvents: [],
    messages: ensureAssistantPlaceholder(context.messages, context.workflowId),
  };

  context.deferredEvents.forEach((event) => {
    next = { ...next, ...applyDomainEvent(next, event) };
  });

  return {
    status: next.status,
    runPhase: next.runPhase,
    events: next.events,
    messages: next.messages,
    cards: next.cards,
    lastEventID: next.lastEventID,
    streamError: next.streamError,
    connectionState: next.connectionState,
    pauseCheckpoint: null,
    deferredEvents: [],
  };
};

const terminalStatusFromEvents = (events: RunEvent[]): RunStatus | null => {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const type = String(events[index].type);
    if (type === "WORKFLOW_COMPLETED" || type === "workflow.completed") return "completed";
    if (type === "WORKFLOW_FAILED" || type === "workflow.failed" || type === "error") return "failed";
    if (type === "WORKFLOW_CANCELLED" || type === "workflow.cancelled") return "cancelled";
  }
  return null;
};

const runEventMessage = (event: RunEvent): string => {
  const raw = (event as { message?: unknown }).message;
  return typeof raw === "string" ? raw.trim() : "";
};

const latestIndex = (events: RunEvent[], predicate: (event: RunEvent) => boolean): number => {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (predicate(events[index])) return index;
  }
  return -1;
};

const latestStatusFromEvents = (
  events: RunEvent[],
  workflowId: string | null,
  ignoredTypes: Set<string> = new Set(),
): { content: string; eventType: string; at: string } | null => {
  if (!workflowId) return null;
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.workflow_id !== workflowId) continue;
    const type = String(event.type);
    if (CONTROL_TIMELINE_TYPES.has(type)) continue;
    if (TELEMETRY_TIMELINE_TYPES.has(type)) continue;
    if (ignoredTypes.has(type)) continue;
    if (type === "WORKFLOW_COMPLETED" || type === "workflow.completed" || type === "WORKFLOW_FAILED" || type === "workflow.failed" || type === "workflow.cancelled") {
      return null;
    }
    const message = runEventMessage(event);
    if (message) {
      return { content: message, eventType: type, at: event.timestamp || new Date().toISOString() };
    }
  }
  return null;
};

const deriveHydratedStatus = (context: SessionContext, state: HydratedState | null | undefined, events: RunEvent[]): RunStatus => {
  const terminalStatus = terminalStatusFromEvents(events);
  if (terminalStatus) return terminalStatus;

  const taskState = state?.task_state;
  const controlState = state?.session_control_state;
  if (
    context.controlIntent?.action === "resume" &&
    (context.status === "running" || context.status === "resuming") &&
    (taskState === "PAUSED" || controlState === "ACTIVE_PAUSED")
  ) {
    return "running";
  }
  if (
    context.controlIntent?.action === "pause" &&
    (context.status === "paused" || context.status === "pausing") &&
    (taskState === "RUNNING" || controlState === "ACTIVE_RUNNING")
  ) {
    return "paused";
  }
  if (taskState === "PAUSED" || controlState === "ACTIVE_PAUSED") return "paused";
  if (taskState === "RUNNING" || controlState === "ACTIVE_RUNNING") return "running";
  if (taskState === "SUCCEEDED") return "completed";
  if (taskState === "FAILED") return "failed";
  if (taskState === "CANCELED") return "cancelled";
  return "idle";
};

const visibleHydratedEvents = (status: RunStatus, events: RunEvent[]): RunEvent[] => {
  if (status !== "paused") return events;
  const lastPause = latestIndex(events, (event) => event.type === "workflow.paused");
  const lastResume = latestIndex(events, (event) => event.type === "workflow.resumed");
  if (lastPause >= 0 && lastResume < lastPause) return events.slice(0, lastPause + 1);
  return events;
};

const hydrateContext = (context: SessionContext, event: Extract<SessionEvent, { type: "HYDRATE" }>): Partial<SessionContext> => {
  const workflowId = event.workflowId || event.state?.active_task_id || context.workflowId;
  const mergedEvents = mergeEvents(context.events, event.events);
  const status = deriveHydratedStatus(context, event.state, mergedEvents);
  const visibleEvents = visibleHydratedEvents(status, mergedEvents);
  const messages = context.messages.length > 0 ? context.messages : event.messages;
  const cards = event.cards.length > 0 ? upsertCards(context.cards, event.cards) : context.cards;
  const base: Partial<SessionContext> = {
    workflowId,
    runId: event.runId || context.runId || workflowId,
    events: visibleEvents,
    cards,
    lastEventID: maxEventID(visibleEvents),
    streamError: null,
    status,
    runPhase: status === "running" ? "streaming" : status === "failed" ? "error" : status === "idle" ? "idle" : "hydrated",
    connectionState: status === "running" ? context.connectionState : "idle",
    deferredEvents: status === "paused" ? context.deferredEvents : [],
    pauseCheckpoint: status === "paused"
      ? { lastEventID: maxEventID(visibleEvents), timestamp: new Date().toISOString() }
      : null,
  };

  if (status === "running") {
    const runningMessages = ensureAssistantPlaceholder(messages, workflowId);
    const latestStatus = latestStatusFromEvents(visibleEvents, workflowId);
    base.messages = latestStatus && workflowId
      ? setStatusMessage(runningMessages, { workflowId, ...latestStatus })
      : removeStatusMessages(runningMessages, workflowId);
  } else if (status === "paused") {
    const pausedMessages = removeEmptyAssistantPlaceholders(clearAssistantLoading(messages), workflowId);
    const latestStatus = latestStatusFromEvents(visibleEvents, workflowId);
    base.messages = latestStatus && workflowId
      ? setStatusMessage(pausedMessages, { workflowId, ...latestStatus })
      : pausedMessages;
  } else if (isTerminalStatus(status)) {
    base.messages = removeStatusMessages(removeEmptyAssistantPlaceholders(clearAssistantLoading(messages), workflowId), workflowId);
  } else {
    base.messages = messages;
  }

  return base;
};

const startWorkflowContext = (context: SessionContext, event: Extract<SessionEvent, { type: "START_WORKFLOW" }>): Partial<SessionContext> => {
  const runId = event.runId || event.workflowId;
  const userMessage = event.query
    ? [{
        id: `user-${event.workflowId}`,
        role: "user" as const,
        content: event.query,
        timestamp: new Date().toISOString(),
        taskId: event.workflowId,
      }]
    : [];

  return {
    workflowId: event.workflowId,
    runId,
    status: "running",
    runPhase: "loading",
    connectionState: "idle",
    streamError: null,
    events: [],
    lastEventID: 0,
    pauseCheckpoint: null,
    deferredEvents: [],
    controlIntent: null,
    messages: ensureAssistantPlaceholder([...context.messages, ...userMessage], event.workflowId),
  };
};

const resumeFromPausedContext = (context: SessionContext): Partial<SessionContext> => {
  const at = new Date().toISOString();
  const checkpointEventID = context.pauseCheckpoint?.lastEventID ?? context.lastEventID;
  const applied = applyDeferredEvents(context);

  if (applied.status && isTerminalStatus(applied.status)) {
    return {
      ...applied,
      controlIntent: null,
    };
  }

  const appliedMessages = applied.messages ?? context.messages;
  const messages = context.deferredEvents.length > 0
    ? appliedMessages
    : removeStatusMessages(appliedMessages, context.workflowId);

  return {
    ...applied,
    status: "running",
    runPhase: "streaming",
    pauseCheckpoint: null,
    controlIntent: {
      action: "resume",
      at,
      checkpointEventID,
    },
    lastEventID: Math.max(checkpointEventID, applied.lastEventID ?? context.lastEventID),
    messages: ensureAssistantPlaceholder(messages, context.workflowId),
  };
};

export const createSessionMachine = (sessionId?: string) => {
  return createMachine(
    {
      id: sessionId ? `session-${sessionId}` : "session",
      context: ({ input }: { input?: string }) => createInitialContext(input || sessionId || "unknown"),
      types: {} as {
        context: SessionContext;
        events: SessionEvent;
        input: string;
      },
      initial: "idle",
      on: {
        START_WORKFLOW: {
          target: ".running",
          actions: assign(({ context, event }) => startWorkflowContext(context, event)),
        },
        HYDRATE: {
          target: ".routing",
          actions: assign(({ context, event }) => hydrateContext(context, event)),
        },
        ADD_MESSAGE: {
          actions: assign({
            messages: ({ context, event }) => [...context.messages, event.message],
          }),
        },
        SET_MESSAGES: {
          actions: assign({
            messages: ({ event }) => event.messages,
          }),
        },
        UPSERT_CARDS: {
          actions: assign({
            cards: ({ context, event }) => upsertCards(context.cards, event.cards),
          }),
        },
        SET_TEMPLATE_PREFLIGHT: {
          actions: assign({
            templatePreflight: ({ event }) => event.preflight,
          }),
        },
        SSE_CONNECTION_STATE: {
          actions: assign({
            connectionState: ({ event }) => event.state,
          }),
        },
        SSE_ERROR: {
          actions: assign({
            streamError: ({ event }) => event.message,
          }),
        },
        SSE_ENVELOPE: {
          actions: assign(({ context, event }) => ingestEnvelope(context, event.envelope)),
        },
        CONTROL_REJECTED: {
          target: ".routing",
          actions: assign(({ context, event }) => {
            const taskId = context.workflowId;
            if (!taskId) return { streamError: event.message };
            const domainEvent = mapControlErrorToDomainEvent({
              taskId,
              sessionId: context.sessionId,
              runId: context.runId,
              message: event.message,
              code: event.code,
            });
            const applied = applyDomainEvent(context, domainEvent);
            const status: RunStatus =
              event.action === "resume"
                ? "paused"
                : event.action === "pause"
                  ? "running"
                  : context.pauseCheckpoint
                    ? "paused"
                    : "running";
            return {
              ...applied,
              status,
              runPhase: status === "running" ? "streaming" : status === "paused" ? "hydrated" : context.runPhase,
              streamError: event.message,
              controlIntent: null,
            };
          }),
        },
      },
      states: {
        routing: {
          always: [
            { guard: ({ context }) => context.status === "running" || context.status === "resuming", target: "running" },
            { guard: ({ context }) => context.status === "paused" || context.status === "pausing", target: "paused" },
            { guard: ({ context }) => context.status === "completed", target: "completed" },
            { guard: ({ context }) => context.status === "failed", target: "failed" },
            { guard: ({ context }) => context.status === "cancelled" || context.status === "cancelling", target: "cancelled" },
            { target: "idle" },
          ],
        },
        idle: {},
        running: {
          invoke: {
            id: SSE_ACTOR_ID,
            src: sseActor,
            input: ({ context }: { context: SessionContext }): SessionSseConfig => ({
              workflowId: context.workflowId!,
              sessionId: context.sessionId,
              lastEventID: context.lastEventID,
              includeLastEventID: shouldReplayBacklogFromCursor(context),
            }),
          },
          entry: sendTo(SSE_ACTOR_ID, ({ context }) => ({
            type: "CONNECT",
            lastEventID: context.lastEventID,
            includeLastEventID: shouldReplayBacklogFromCursor(context),
          })),
          always: [
            { guard: ({ context }) => context.status === "completed", target: "completed" },
            { guard: ({ context }) => context.status === "failed", target: "failed" },
            { guard: ({ context }) => context.status === "cancelled", target: "cancelled" },
            { guard: ({ context }) => context.status === "paused", target: "paused" },
          ],
          on: {
            PAUSE: {
              target: "paused",
              actions: assign(({ context }) => {
                const at = new Date().toISOString();
                return {
                  status: "paused" as RunStatus,
                  runPhase: "hydrated" as RunPhase,
                  connectionState: "idle" as ConnectionState,
                  pauseCheckpoint: {
                    lastEventID: context.lastEventID,
                    timestamp: at,
                  },
                  controlIntent: {
                    action: "pause",
                    at,
                    checkpointEventID: context.lastEventID,
                  } satisfies LocalControlIntent,
                  messages: context.workflowId
                    ? setStatusMessage(
                        removeEmptyAssistantPlaceholders(clearAssistantLoading(context.messages), context.workflowId),
                        {
                          workflowId: context.workflowId,
                          content: "Paused",
                          at,
                          eventType: "workflow.paused",
                        },
                      )
                    : removeEmptyAssistantPlaceholders(clearAssistantLoading(context.messages), context.workflowId),
                };
              }),
            },
            CANCEL: {
              target: "cancelled",
              actions: assign(({ context }) => ({
                status: "cancelled" as RunStatus,
                runPhase: "hydrated" as RunPhase,
                connectionState: "idle" as ConnectionState,
                pauseCheckpoint: null,
                deferredEvents: [],
                controlIntent: null,
                messages: removeStatusMessages(removeEmptyAssistantPlaceholders(clearAssistantLoading(context.messages), context.workflowId), context.workflowId),
              })),
            },
          },
        },
        paused: {
          always: [
            { guard: ({ context }) => context.status === "completed", target: "completed" },
            { guard: ({ context }) => context.status === "failed", target: "failed" },
            { guard: ({ context }) => context.status === "cancelled", target: "cancelled" },
            { guard: ({ context }) => context.status === "running" || context.status === "resuming", target: "running" },
          ],
          on: {
            RESUME: {
              target: "running",
              actions: assign(({ context }) => resumeFromPausedContext(context)),
            },
            CANCEL: {
              target: "cancelled",
              actions: assign(({ context }) => ({
                status: "cancelled" as RunStatus,
                runPhase: "hydrated" as RunPhase,
                connectionState: "idle" as ConnectionState,
                pauseCheckpoint: null,
                deferredEvents: [],
                controlIntent: null,
                messages: removeStatusMessages(removeEmptyAssistantPlaceholders(clearAssistantLoading(context.messages), context.workflowId), context.workflowId),
              })),
            },
          },
        },
        completed: {
          on: {
            PAUSE: { actions: () => undefined },
            RESUME: { actions: () => undefined },
            CANCEL: { actions: () => undefined },
          },
        },
        failed: {},
        cancelled: {},
      },
    },
  );
};
