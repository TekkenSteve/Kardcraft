import { describe, expect, it, vi } from "vitest";
import { createBrowserSessionAuthClient } from "./auth-client";
import { emitAuthStateChanged } from "./auth-events";

describe("browser session auth client", () => {
    it("does not treat file-picker focus as an auth state change", () => {
        const originalWindow = globalThis.window;
        const originalDocument = globalThis.document;
        const fakeWindow = new EventTarget();
        const fakeDocument = new EventTarget();
        Object.defineProperty(globalThis, "window", {
            value: fakeWindow,
            configurable: true,
        });
        Object.defineProperty(globalThis, "document", {
            value: fakeDocument,
            configurable: true,
        });

        const listener = vi.fn();
        const unsubscribe = createBrowserSessionAuthClient().onAuthStateChanged(listener);

        window.dispatchEvent(new Event("focus"));
        document.dispatchEvent(new Event("visibilitychange"));
        expect(listener).not.toHaveBeenCalled();

        emitAuthStateChanged();
        expect(listener).toHaveBeenCalledTimes(1);

        unsubscribe();
        Object.defineProperty(globalThis, "window", {
            value: originalWindow,
            configurable: true,
        });
        Object.defineProperty(globalThis, "document", {
            value: originalDocument,
            configurable: true,
        });
    });
});
