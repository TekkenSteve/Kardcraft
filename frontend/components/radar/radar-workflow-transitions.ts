import { UIState } from "../../lib/radar/store";
import { WorkItem } from "../../lib/radar/types";

type RadarStoreLike = {
    getState: () => Pick<UIState, "items" | "applyTick">;
};

type TimeoutScheduler = (callback: () => void, delayMs: number) => number;
type TimeoutClearer = (handle: number) => void;

const itemWorkflowId = (itemId: string): string => itemId.split("::")[0] || "";

export const listWorkflowInProgressItemIds = (
    items: Record<string, WorkItem>,
    workflowId: string,
): string[] =>
    Object.entries(items)
        .filter(([id, item]) => itemWorkflowId(id) === workflowId && item.status === "in_progress")
        .map(([id]) => id);

export const applyWorkflowPausedTransition = (
    store: RadarStoreLike,
    workflowId: string,
    tickStart: number,
): { nextTick: number; affectedItemIds: string[] } => {
    const itemIds = listWorkflowInProgressItemIds(store.getState().items, workflowId);
    let tick = tickStart;
    for (const itemId of itemIds) {
        tick += 1;
        store.getState().applyTick({
            tick_id: tick,
            items: [{ id: itemId, status: "blocked" }],
        });
    }
    return { nextTick: tick, affectedItemIds: itemIds };
};

export const applyWorkflowTerminalTransition = (
    store: RadarStoreLike,
    workflowId: string,
    tickStart: number,
    options: {
        schedule: TimeoutScheduler;
        clear: TimeoutClearer;
        timeoutRefs: Map<string, number>;
        onRemoved?: (itemId: string) => void;
        accelerateMs?: number;
        removeDelayMs?: number;
    },
): { nextTick: number; affectedItemIds: string[] } => {
    const accelerateMs = options.accelerateMs ?? 300;
    const removeDelayMs = options.removeDelayMs ?? 500;
    const itemIds = listWorkflowInProgressItemIds(store.getState().items, workflowId);
    let tick = tickStart;

    for (const itemId of itemIds) {
        tick += 1;
        store.getState().applyTick({
            tick_id: tick,
            items: [{ id: itemId, eta_ms: accelerateMs, estimate_ms: accelerateMs }],
        });

        const previous = options.timeoutRefs.get(itemId);
        if (previous) options.clear(previous);
        const handle = options.schedule(() => {
            tick += 1;
            store.getState().applyTick({
                tick_id: tick,
                items: [{ id: itemId, status: "done" }],
                agents_remove: [itemId],
            });
            options.timeoutRefs.delete(itemId);
            options.onRemoved?.(itemId);
        }, removeDelayMs);
        options.timeoutRefs.set(itemId, handle);
    }

    return { nextTick: tick, affectedItemIds: itemIds };
};
