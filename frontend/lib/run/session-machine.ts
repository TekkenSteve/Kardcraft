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
  conversation_status?: RunStatus | null;
};

export type ConversationInterrupt = {
  interrupt_id: string;
  type: string;
  prompt: string;
  input_schema?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
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
  persistedMessages: RunMessage[];
  streamingOverlay: Record<string, RunMessage>;
  messages: RunMessage[];
  interrupt: ConversationInterrupt | null;
  cards: CardData[];
  lastEventID: number;
  pauseCheckpoint: { lastEventID: number; timestamp: string } | null;
  deferredEvents: RunDomainEvent[];
  controlIntent: LocalControlIntent | null;
  templatePreflight: TemplatePreflightState;
};

export type SessionEvent =
  | { type: "START_WORKFLOW"; workflowId: string; runId?: string | null; query?: string; cursor?: number; userMessage?: RunMessage }
  | { type: "HYDRATE"; workflowId: string | null; runId: string | null; messages: RunMessage[]; events: RunEvent[]; cards: CardData[]; cursor?: number; interrupt?: ConversationInterrupt | null; state?: HydratedState | null }
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
  persistedMessages: [],
  streamingOverlay: {},
  messages: [],
  interrupt: null,
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
  "WORKFLOW_PAUSED",
  "WORKFLOW_RESUMED",
  "workflow.cancelling",
  "WORKFLOW_CANCELLING",
]);

const TELEMETRY_TIMELINE_TYPES = new Set<string>([
  "LLM_USAGE_RECORDED",
]);

const TERMINAL_STATUSES = new Set<RunStatus>(["completed", "failed", "cancelled"]);

const isTerminalStatus = (status: RunStatus) => TERMINAL_STATUSES.has(status);

const shouldReplayBacklogFromCursor = (context: SessionContext): boolean =>
  context.controlIntent?.action === "resume" &&
  context.lastEventID <= context.controlIntent.checkpointEventID;

const extractRunEventSequence = (event: RunEvent): number => {
  const streamID = (event as { stream_id?: unknown }).stream_id;
  if (typeof streamID !== "string" || !streamID.startsWith("agentos:")) return 0;
  const payload = (event as { payload?: unknown }).payload;
  if (!payload || typeof payload !== "object") return 0;
  const raw = (payload as Record<string, unknown>).sequence;
  if (typeof raw === "number" && Number.isFinite(raw)) return Math.floor(raw);
  if (typeof raw === "string") {
    const parsed = Number(raw);
    if (Number.isFinite(parsed)) return Math.floor(parsed);
  }
  return 0;
};

const extractRunEventID = (event: RunEvent): number => {
  const sequence = (event as { seq?: unknown }).seq;
  if (typeof sequence === "number" && Number.isSafeInteger(sequence) && sequence > 0) return sequence;
  const legacyID = (event as { id?: unknown }).id;
  const parsed = typeof legacyID === "number" ? legacyID : Number(legacyID);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : 0;
};

const extractEnvelopeEventID = (envelope: RuntimeEnvelope): number => {
  return Number.isSafeInteger(envelope.sequence) && envelope.sequence > 0 ? envelope.sequence : 0;
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

const maxEventID = (events: RunEvent[]): number => events.reduce((max, event) => Math.max(max, extractRunEventSequence(event)), 0);

const upsertCards = (current: CardData[], incoming: CardData[]): CardData[] => {
  const byId = new Map(current.map((card) => [card.card_id, card]));
  incoming.forEach((card) => byId.set(card.card_id, card));
  return Array.from(byId.values());
};

const mergeVisibleMessages = (persisted: RunMessage[], overlay: Record<string, RunMessage>): RunMessage[] => [
  ...persisted,
  ...Object.values(overlay).filter((message) => message.content.length > 0),
];

const upsertPersistedMessage = (messages: RunMessage[], incoming: RunMessage): RunMessage[] => {
  const index = messages.findIndex((message) => message.id === incoming.id);
  if (index < 0) return [...messages, incoming];
  const next = [...messages];
  next[index] = { ...messages[index], ...incoming, isStreaming: false, isGenerating: false };
  return next;
};

const clearRunOverlay = (overlay: Record<string, RunMessage>, runId: string | null | undefined) => {
  if (!runId) return {};
  return Object.fromEntries(Object.entries(overlay).filter(([, message]) => message.runId !== runId));
};

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
      updates.interrupt = null;
      break;

    case "run.finished": {
      const streamingOverlay = clearRunOverlay(context.streamingOverlay, event.runId);
      updates.streamingOverlay = streamingOverlay;
      updates.messages = mergeVisibleMessages(context.persistedMessages, streamingOverlay);
      updates.connectionState = "idle";
      updates.controlIntent = null;
      if (event.outcome === "interrupt") {
        updates.status = "waiting_input";
        updates.runPhase = "hydrated";
        updates.interrupt = event.interrupt || null;
      } else {
        updates.status = event.outcome === "cancelled" ? "cancelled" : "completed";
        updates.runPhase = "hydrated";
        updates.interrupt = null;
      }
      break;
    }

    case "workflow.completed": {
      updates.status = "completed";
      updates.runPhase = "hydrated";
      updates.connectionState = "idle";
      updates.pauseCheckpoint = null;
      updates.deferredEvents = [];
      updates.controlIntent = null;
      updates.streamingOverlay = {};
      updates.messages = context.persistedMessages;
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
      {
        const streamingOverlay = clearRunOverlay(context.streamingOverlay, event.runId);
        updates.streamingOverlay = streamingOverlay;
        updates.messages = mergeVisibleMessages(context.persistedMessages, streamingOverlay);
      }
      updates.interrupt = null;
      break;

    case "message.started": {
      const streamingOverlay = {
        ...context.streamingOverlay,
        [event.messageId]: {
          id: event.messageId,
          role: "assistant" as const,
          content: "",
          isStreaming: true,
          taskId: event.workflowId,
          runId: event.runId || undefined,
          timestamp: event.at,
        },
      };
      updates.streamingOverlay = streamingOverlay;
      updates.messages = mergeVisibleMessages(context.persistedMessages, streamingOverlay);
      break;
    }

    case "message.delta": {
      const current = context.streamingOverlay[event.messageId];
      const streamingOverlay = {
        ...context.streamingOverlay,
        [event.messageId]: {
          id: event.messageId,
          role: "assistant" as const,
          content: `${current?.content || ""}${event.delta}`,
          isStreaming: true,
          taskId: event.workflowId,
          runId: event.runId || undefined,
          timestamp: current?.timestamp || event.at,
        },
      };
      updates.streamingOverlay = streamingOverlay;
      updates.messages = mergeVisibleMessages(context.persistedMessages, streamingOverlay);
      break;
    }

    case "message.completed": {
      const persistedMessages = upsertPersistedMessage(context.persistedMessages, {
        id: event.messageId,
        role: "assistant",
        content: event.content,
        taskId: event.workflowId,
        runId: event.runId || undefined,
        timestamp: event.at,
        metadata: event.metadata,
      });
      const streamingOverlay = { ...context.streamingOverlay };
      delete streamingOverlay[event.messageId];
      updates.persistedMessages = persistedMessages;
      updates.streamingOverlay = streamingOverlay;
      updates.messages = mergeVisibleMessages(persistedMessages, streamingOverlay);
      break;
    }

    case "workspace.updated":
      updates.cards = upsertCards(context.cards, event.cards);
      break;

    case "timeline.event":
      // Extension events are timeline/process diagnostics only. They never own chat state.
      break;

    case "control.cancel.confirmed":
      updates.status = "cancelled";
      updates.runPhase = "hydrated";
      updates.connectionState = "idle";
      updates.pauseCheckpoint = null;
      updates.deferredEvents = [];
      updates.controlIntent = null;
      updates.streamingOverlay = {};
      updates.messages = context.persistedMessages;
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
    sequence: envelope.sequence,
    payload,
    fallbackWorkflowId: envelope.process_id || envelope.run_id,
    fallbackSessionId: envelope.thread_id,
    at: envelope.occurred_at,
    eventId: envelope.event_id,
  });
};

const ingestEnvelope = (context: SessionContext, envelope: RuntimeEnvelope): Partial<SessionContext> => {
  const eventID = extractEnvelopeEventID(envelope);
  if (eventID <= context.lastEventID) return {};
  const mapped = envelopeToDomainEvent(context, envelope);
  if (!mapped.ok) {
    return {
      lastEventID: Math.max(context.lastEventID, eventID),
    };
  }

  if (context.workflowId && envelope.process_id && "workflowId" in mapped.event && mapped.event.workflowId !== context.workflowId) {
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
      messages: mergeVisibleMessages(context.persistedMessages, context.streamingOverlay),
    };
  }

  let next: SessionContext = {
    ...context,
    status: "running",
    runPhase: "streaming",
    pauseCheckpoint: null,
    deferredEvents: [],
    messages: mergeVisibleMessages(context.persistedMessages, context.streamingOverlay),
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
    if (type === "WORKFLOW_COMPLETED") return "completed";
    if (type === "WORKFLOW_FAILED" || type === "error") return "failed";
    if (type === "WORKFLOW_CANCELLED") return "cancelled";
  }
  return null;
};

const latestWaitingInputEvent = (events: RunEvent[], workflowId: string | null): RunEvent | null => {
  if (!workflowId) return null;
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.workflow_id !== workflowId) continue;
    if (event.type === "WORKFLOW_WAITING_INPUT") return event;
    if (event.type === "WORKFLOW_STARTED" || event.type === "MESSAGE_RECEIVED" || event.type === "WORKFLOW_RESUMED") return null;
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
    if (type === "WORKFLOW_COMPLETED" || type === "WORKFLOW_FAILED" || type === "WORKFLOW_CANCELLED") {
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
  if (state?.conversation_status) return state.conversation_status;
  const terminalStatus = terminalStatusFromEvents(events);
  if (terminalStatus) return terminalStatus;
  if (latestWaitingInputEvent(events, context.workflowId || state?.active_task_id || null)) return "waiting_input";

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
  const lastPause = latestIndex(events, (event) => event.type === "WORKFLOW_PAUSED");
  const lastResume = latestIndex(events, (event) => event.type === "WORKFLOW_RESUMED");
  if (lastPause >= 0 && lastResume < lastPause) return events.slice(0, lastPause + 1);
  return events;
};

const hydrateContext = (context: SessionContext, event: Extract<SessionEvent, { type: "HYDRATE" }>): Partial<SessionContext> => {
  const workflowId = event.workflowId || event.state?.active_task_id || context.workflowId;
  const mergedEvents = mergeEvents(context.events, event.events);
  const status = deriveHydratedStatus(context, event.state, mergedEvents);
  const visibleEvents = visibleHydratedEvents(status, mergedEvents);
  const messages = event.messages;
  const cards = event.cards.length > 0 ? upsertCards(context.cards, event.cards) : context.cards;
  const base: Partial<SessionContext> = {
    workflowId,
    runId: event.runId || context.runId || workflowId,
    events: visibleEvents,
    cards,
    lastEventID: event.cursor ?? maxEventID(visibleEvents),
    streamError: null,
    status,
    runPhase: status === "running" ? "streaming" : status === "failed" ? "error" : status === "idle" ? "idle" : "hydrated",
    connectionState: status === "running" ? context.connectionState : "idle",
    deferredEvents: status === "paused" ? context.deferredEvents : [],
    pauseCheckpoint: status === "paused"
      ? { lastEventID: maxEventID(visibleEvents), timestamp: new Date().toISOString() }
      : null,
    persistedMessages: messages,
    streamingOverlay: {},
    messages,
    interrupt: event.interrupt ?? null,
  };

  return base;
};

const startWorkflowContext = (context: SessionContext, event: Extract<SessionEvent, { type: "START_WORKFLOW" }>): Partial<SessionContext> => {
  const runId = event.runId || event.workflowId;
  const userMessage = event.userMessage ? [event.userMessage] : event.query
    ? [{
        id: `user-${event.workflowId}`,
        role: "user" as const,
        content: event.query,
        timestamp: new Date().toISOString(),
        taskId: event.workflowId,
        runId,
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
    lastEventID: event.cursor ?? 0,
    pauseCheckpoint: null,
    deferredEvents: [],
    controlIntent: null,
    persistedMessages: [...context.persistedMessages, ...userMessage],
    streamingOverlay: {},
    messages: [...context.persistedMessages, ...userMessage],
    interrupt: null,
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
    : appliedMessages;

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
    messages,
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
          actions: assign(({ context, event }) => {
            const persistedMessages = upsertPersistedMessage(context.persistedMessages, event.message);
            return { persistedMessages, messages: mergeVisibleMessages(persistedMessages, context.streamingOverlay) };
          }),
        },
        SET_MESSAGES: {
          actions: assign({ persistedMessages: ({ event }) => event.messages, streamingOverlay: {}, messages: ({ event }) => event.messages }),
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
            { guard: ({ context }) => context.status === "waiting_input", target: "waitingInput" },
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
              sessionId: context.sessionId,
              lastEventID: context.lastEventID,
              includeLastEventID: true,
            }),
          },
          entry: sendTo(SSE_ACTOR_ID, ({ context }) => ({
            type: "CONNECT",
            lastEventID: context.lastEventID,
            includeLastEventID: true,
          })),
          always: [
            { guard: ({ context }) => context.status === "waiting_input", target: "waitingInput" },
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
                  messages: mergeVisibleMessages(context.persistedMessages, context.streamingOverlay),
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
                streamingOverlay: {},
                messages: context.persistedMessages,
              })),
            },
          },
        },
        waitingInput: {
          on: {
            CANCEL: {
              target: "cancelled",
              actions: assign(({ context }) => ({
                status: "cancelled" as RunStatus,
                runPhase: "hydrated" as RunPhase,
                connectionState: "idle" as ConnectionState,
                pauseCheckpoint: null,
                deferredEvents: [],
                controlIntent: null,
                streamingOverlay: {},
                messages: context.persistedMessages,
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
                streamingOverlay: {},
                messages: context.persistedMessages,
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
