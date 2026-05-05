const originalEventSource = globalThis.EventSource;

class EventSourceStub {
  readyState = 1;
  onopen: ((event: Event) => unknown) | null = null;
  onmessage: ((event: MessageEvent) => unknown) | null = null;
  onerror: ((event: Event) => unknown) | null = null;
  addEventListener() {}
  removeEventListener() {}
  close() {}
}

// Vitest node runtime does not provide EventSource.
if (typeof globalThis.EventSource === "undefined") {
  globalThis.EventSource = EventSourceStub as unknown as typeof EventSource;
}

// @microsoft/fetch-event-source references window/document as globals for
// visibilitychange and setTimeout/clearTimeout during abort cleanup. Provide
// stubs for Node.js test environment to prevent unhandled ReferenceErrors.
if (typeof globalThis.window === "undefined") {
  (globalThis as any).window = {
    setTimeout: globalThis.setTimeout.bind(globalThis),
    clearTimeout: globalThis.clearTimeout.bind(globalThis),
    fetch: globalThis.fetch.bind(globalThis),
  };
}
if (typeof globalThis.document === "undefined") {
  (globalThis as any).document = {
    hidden: false,
    addEventListener: () => {},
    removeEventListener: () => {},
  };
}

export function restoreEventSourceForTests() {
  globalThis.EventSource = originalEventSource;
}
