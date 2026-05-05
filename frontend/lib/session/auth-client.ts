import {
    ory,
    type Session,
    type UpdateLoginFlowBody,
} from "@/lib/kratos/client";
import { emitAuthStateChanged, subscribeAuthStateChanged } from "./auth-events";

export type SessionLoginRequest = {
    flowId: string;
    body: UpdateLoginFlowBody;
};

export interface SessionAuthClient {
    getSession: () => Promise<Session | null>;
    login: (request: SessionLoginRequest) => Promise<void>;
    logout: () => Promise<void>;
    onAuthStateChanged: (listener: () => void) => () => void;
}

const asHttpStatus = (error: unknown): number | null => {
    if (!error || typeof error !== "object") return null;
    const maybeResponse = (error as { response?: { status?: unknown } }).response;
    if (!maybeResponse || typeof maybeResponse.status !== "number") return null;
    return maybeResponse.status;
};

export function createBrowserSessionAuthClient(): SessionAuthClient {
    return {
        getSession: async () => {
            try {
                const { data } = await ory.toSession();
                return data;
            } catch (error) {
                const status = asHttpStatus(error);
                if (status === 401) return null;
                throw error;
            }
        },
        login: async (request) => {
            await ory.updateLoginFlow({
                flow: request.flowId,
                updateLoginFlowBody: request.body,
            });
            emitAuthStateChanged();
        },
        logout: async () => {
            const { data } = await ory.createBrowserLogoutFlow();
            await ory.updateLogoutFlow({
                token: data.logout_token,
            });
            emitAuthStateChanged();
        },
        onAuthStateChanged: (listener) => {
            if (typeof window === "undefined") {
                return () => undefined;
            }

            return subscribeAuthStateChanged(listener);
        },
    };
}
