import { describe, expect, it } from "vitest";
import { createActor } from "xstate";
import { APP_SESSION_REGISTRY_ACTOR_ID, createAppMachine } from "./app-machine";

describe("app machine", () => {
    it("starts with session registry child actor", () => {
        const actor = createActor(createAppMachine());
        actor.start();

        const snapshot = actor.getSnapshot();
        expect(snapshot.value).toBe("running");
        expect(snapshot.children[APP_SESSION_REGISTRY_ACTOR_ID]).toBeDefined();

        actor.stop();
    });
});
