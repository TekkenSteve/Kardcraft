import { afterEach, describe, expect, it, vi } from "vitest";
import { createActor, createMachine, sendTo } from "xstate";
import type { EventSourceMessage, FetchEventSourceInit } from "@microsoft/fetch-event-source";
import type { RuntimeEnvelope } from "./runtime-envelope";

const fetchCalls = vi.hoisted(() => [] as Array<{ input: RequestInfo; init: FetchEventSourceInit }>);

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: vi.fn((input: RequestInfo, init: FetchEventSourceInit) => {
    fetchCalls.push({ input, init });
    return new Promise<void>(() => undefined);
  }),
}));

import {
  createSessionSseActor,
  SESSION_SSE_STALE_CONNECTION_MS,
  SESSION_SSE_WATCHDOG_INTERVAL_MS,
} from "./session-sse-actor";

const makeEnvelope = (overrides: Partial<RuntimeEnvelope> & Pick<RuntimeEnvelope, "event_type" | "event_id">): RuntimeEnvelope => {
  const { event_id: eventId, event_type: eventType, ...rest } = overrides;
  return {
    schema_version: "agentos.conversation.v1",
    event_id: eventId,
    event_type: eventType,
    sequence: 1,
    occurred_at: new Date().toISOString(),
    process_id: "wf-1",
    run_id: "run-1",
    thread_id: "s-1",
    payload: {},
    ...rest,
  };
};

function createHarness() {
  const machine = createMachine({
    invoke: {
      id: "sse",
      src: createSessionSseActor(),
      input: {
        workflowId: "wf-1",
        sessionId: "s-1",
      },
    },
    entry: sendTo("sse", { type: "CONNECT" }),
  });
  const actor = createActor(machine);
  actor.start();
  return actor;
}

describe("session SSE actor", () => {
  afterEach(() => {
    fetchCalls.splice(0, fetchCalls.length);
    vi.useRealTimers();
  });

  it("reconnects a stale open stream from the latest numeric SSE cursor", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-05T00:00:00.000Z"));

    const actor = createHarness();

    await vi.waitFor(() => expect(fetchCalls).toHaveLength(1));
    await fetchCalls[0].init.onopen?.(new Response(null, { status: 200 }));

    const message: EventSourceMessage = {
      id: "106",
      event: "NODE_COMPLETED",
      data: JSON.stringify(makeEnvelope({ event_type: "NODE_COMPLETED", event_id: "wf-1:106", sequence: 106 })),
      retry: undefined,
    };
    fetchCalls[0].init.onmessage?.(message);

    await vi.advanceTimersByTimeAsync(SESSION_SSE_STALE_CONNECTION_MS - 1);
    expect(fetchCalls).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(SESSION_SSE_WATCHDOG_INTERVAL_MS);

    expect(fetchCalls).toHaveLength(2);
    expect(fetchCalls[0].init.signal?.aborted).toBe(true);
    expect(String(fetchCalls[1].input)).toContain("after=106");

    actor.stop();
  });
});
