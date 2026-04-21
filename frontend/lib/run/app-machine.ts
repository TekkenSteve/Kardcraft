import { createMachine } from "xstate";
import { createSessionRegistryMachine } from "./session-registry-machine";

export const APP_SESSION_REGISTRY_ACTOR_ID = "sessionRegistry";

export function createAppMachine() {
    return createMachine({
        id: "app",
        initial: "running",
        states: {
            running: {
                invoke: {
                    id: APP_SESSION_REGISTRY_ACTOR_ID,
                    src: createSessionRegistryMachine(),
                },
            },
        },
    });
}
