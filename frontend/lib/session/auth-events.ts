export const AUTH_STATE_CHANGED_EVENT = "auth-state-changed";

export function emitAuthStateChanged(): void {
    if (typeof window === "undefined") return;
    window.dispatchEvent(new CustomEvent(AUTH_STATE_CHANGED_EVENT));
}

export function subscribeAuthStateChanged(listener: () => void): () => void {
    if (typeof window === "undefined") {
        return () => undefined;
    }

    const handleChange = () => listener();
    window.addEventListener(AUTH_STATE_CHANGED_EVENT, handleChange);

    return () => {
        window.removeEventListener(AUTH_STATE_CHANGED_EVENT, handleChange);
    };
}
