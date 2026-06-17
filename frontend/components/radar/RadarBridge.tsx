"use client";

import { useEffect, useRef } from "react";
import { radarStore } from "@/lib/radar/store";
import { useActiveRunSession } from "@/lib/run/system";
import { applyWorkflowPausedTransition, applyWorkflowTerminalTransition } from "./radar-workflow-transitions";

// Longer estimate = slower flight to center (more time to see the animation)
const DEFAULT_ESTIMATE_MS = 45000; // ~45s to center (matches original dashboard)

// Internal system agents that shouldn't appear on the radar visualization
const INTERNAL_AGENTS = new Set([
  "orchestrator",
  "planner",
  "title_generator",
  "title-generator",
  "router",
  "decomposer",
  "synthesizer",
  "system",
]);

// Check if an agent ID is internal/should be hidden
function isInternalAgent(agentId: string): boolean {
  if (!agentId) return true;
  const normalized = agentId.toLowerCase().trim();
  const [namePrefix, nameMarker] = normalized.split("-", 2);
  if (namePrefix === "agent" && nameMarker === "undefined") return true;
  if (normalized === "undefined" || normalized === "unknown") return true;
  return INTERNAL_AGENTS.has(normalized);
}

/**
 * Bridge component that maps Redux SSE events to the radar store.
 * Renders nothing - just keeps the radar store in sync with Redux events.
 */
export function RadarBridge() {
  const activeSession = useActiveRunSession();
  const events = activeSession.events;
  const status = activeSession.status;
  const processedRef = useRef<Set<string>>(new Set());
  const tickRef = useRef<number>(0);
  const timeoutRefs = useRef<Map<string, number>>(new Map());
  const initializedRef = useRef<boolean>(false);
  // Track when each flight started (don't reset on subsequent events)
  const flightStartTimes = useRef<Map<string, number>>(new Map());

  // Track previous status for detecting completion
  const prevStatusRef = useRef<string>(status);
  const isLiveStatus = status === "running" || status === "paused" || status === "resuming" || status === "cancelling";

  // Initialize/reset store when status changes to idle or starts a fresh live run.
  useEffect(() => {
    if (status === "idle" || (isLiveStatus && !initializedRef.current)) {
      // Clear pending timers
      for (const t of timeoutRefs.current.values()) window.clearTimeout(t);
      timeoutRefs.current.clear();
      processedRef.current.clear();
      flightStartTimes.current.clear();

      // Reset store
      radarStore.getState().reset();
      tickRef.current = 0;
      initializedRef.current = isLiveStatus;
    }
    prevStatusRef.current = status;
  }, [isLiveStatus, status]);

  // When task reaches terminal state, accelerate all flights to center.
  useEffect(() => {
    const wasLive = prevStatusRef.current === "running" || prevStatusRef.current === "paused" || prevStatusRef.current === "cancelling";
    const isNowComplete = status === "completed" || status === "cancelled" || status === "failed" || status === "idle";
    
    if (wasLive && isNowComplete) {
      // Accelerate all in-progress flights to center
      const state = radarStore.getState();
      for (const [itemId, item] of Object.entries(state.items)) {
        if (item.status === "in_progress") {
          const tick = ++tickRef.current;
          radarStore.getState().applyTick({
            tick_id: tick,
            items: [{ id: itemId, eta_ms: 300, estimate_ms: 300 }],
          });
          
          // Remove after animation completes
          const handle = window.setTimeout(() => {
            const tick2 = ++tickRef.current;
            radarStore.getState().applyTick({
              tick_id: tick2,
              items: [{ id: itemId, status: "done" }],
              agents_remove: [itemId],
            });
            flightStartTimes.current.delete(itemId);
          }, 500);
          
          const prev = timeoutRefs.current.get(itemId);
          if (prev) window.clearTimeout(prev);
          timeoutRefs.current.set(itemId, handle);
        }
      }
    }
  }, [status]);

  // Process events
  useEffect(() => {
    if (!isLiveStatus) return;

    // Events that spawn or keep a flight active (agent is working)
    const activeLike = new Set([
      "AGENT_STARTED",
      "AGENT_THINKING",
      "MESSAGE_SENT",
      "TOOL_INVOKED",
      "MESSAGE_RECEIVED",
      "ROLE_ASSIGNED",
      "DELEGATION",
      "DATA_PROCESSING",
      "PROGRESS",
    ]);
    // Events that complete a flight (agent finished this task)
    const doneLike = new Set(["AGENT_COMPLETED", "TOOL_COMPLETED"]);

    for (const ev of events) {
      const workflowId = ev.workflow_id || "unknown";
      const agentId = ev.agent_id || `agent-${ev.seq}`;
      
      // Skip internal system agents - only show user-facing agent activity
      if (isInternalAgent(agentId)) continue;
      
      // One flight per agent - reuse same ID for all events from the same agent
      const id = `${workflowId}::${agentId}`;

      // Deduplicate by event key
      const key = ev.stream_id || `${workflowId}::${ev.seq}::${ev.type}::${agentId}`;
      if (processedRef.current.has(key)) continue;
      processedRef.current.add(key);

      // Use current time for flight animation (not event timestamp which may be historical)
      const now = Date.now();

      // Active events: spawn new flight OR keep existing one flying
      if (activeLike.has(ev.type)) {
        const existing = radarStore.getState().items[id];
        
        if (!existing) {
          // NEW flight - spawn at edge with CURRENT time (not historical event time)
          const tick = ++tickRef.current;
          flightStartTimes.current.set(id, now);
          
          radarStore.getState().applyTick({
            tick_id: tick,
            items: [
              {
                id,
                group: "A",
                sector: "PLANNING",
                depends_on: [],
                estimate_ms: DEFAULT_ESTIMATE_MS,
                started_at: now,
                status: "in_progress",
                agent_id: agentId,
                tps_min: 1,
                tps_max: 1,
                tps: 1,
                tokens_done: 0,
                est_tokens: 0,
              },
            ],
            agents: [{ id, work_item_id: id, x: 0, y: 0, v: 0.002, curve_phase: 0 }],
          });
        }
        // If existing, do nothing - let it keep flying based on original started_at
        continue;
      }

      // Completion events: let flight reach center naturally, then pulse and remove
      if (doneLike.has(ev.type)) {
        const existing = radarStore.getState().items[id];
        
        if (existing && existing.status === "in_progress") {
          // Calculate how far the agent has flown
          const startTime = flightStartTimes.current.get(id) || existing.started_at || now;
          const elapsed = now - startTime;
          const progress = Math.min(1, elapsed / DEFAULT_ESTIMATE_MS);
          
          // If agent hasn't reached center yet, give it time to arrive
          // Set eta_ms based on remaining distance, minimum 500ms for visual
          const remainingMs = Math.max(500, (1 - progress) * DEFAULT_ESTIMATE_MS * 0.3);
          
          const tick1 = ++tickRef.current;
          radarStore.getState().applyTick({
            tick_id: tick1,
            items: [
              {
                id,
                // Accelerate to center: reduce estimate so progress catches up
                estimate_ms: elapsed + remainingMs,
                eta_ms: remainingMs,
                status: "in_progress",
              },
            ],
          });

          // After the flight completes, mark done and remove
          const handle = window.setTimeout(() => {
            const tick2 = ++tickRef.current;
            radarStore.getState().applyTick({
              tick_id: tick2,
              items: [{ id, status: "done" }],
              agents_remove: [id],
            });
            timeoutRefs.current.delete(id);
            flightStartTimes.current.delete(id);
          }, remainingMs + 200); // Extra time for pulse animation

          const prev = timeoutRefs.current.get(id);
          if (prev) window.clearTimeout(prev);
          timeoutRefs.current.set(id, handle);
        }
        continue;
      }

      // Terminal events: complete all remaining flights for this workflow
      if (ev.type === "WORKFLOW_COMPLETED" || ev.type === "WORKFLOW_CANCELLED" || ev.type === "WORKFLOW_FAILED") {
        const result = applyWorkflowTerminalTransition(radarStore, workflowId, tickRef.current, {
          schedule: (callback, delayMs) => window.setTimeout(callback, delayMs),
          clear: (handle) => window.clearTimeout(handle),
          timeoutRefs: timeoutRefs.current,
          onRemoved: (itemId) => {
            flightStartTimes.current.delete(itemId);
          },
        });
        tickRef.current = result.nextTick;
        continue;
      }

      // Pause event: stop all in-progress flights for that workflow.
      if (ev.type === "WORKFLOW_PAUSED") {
        const result = applyWorkflowPausedTransition(radarStore, workflowId, tickRef.current);
        tickRef.current = result.nextTick;
        continue;
      }

      // Error: mark as blocked and remove
      if (ev.type === "error") {
        const tick = ++tickRef.current;
        radarStore.getState().applyTick({
          tick_id: tick,
          items: [{ id, status: "blocked" }],
          agents_remove: [id],
        });
        flightStartTimes.current.delete(id);
        continue;
      }

      // Fallback: spawn flight for any other event if not seen
      const existing = radarStore.getState().items[id];
      if (!existing) {
        const tick = ++tickRef.current;
        flightStartTimes.current.set(id, now);
        
        radarStore.getState().applyTick({
          tick_id: tick,
          items: [
            {
              id,
              group: "A",
              sector: "PLANNING",
              depends_on: [],
              estimate_ms: DEFAULT_ESTIMATE_MS,
              started_at: now,
              status: "in_progress",
              agent_id: agentId,
              tps_min: 1,
              tps_max: 1,
              tps: 1,
              tokens_done: 0,
              est_tokens: 0,
            },
          ],
          agents: [{ id, work_item_id: id, x: 0, y: 0, v: 0.002, curve_phase: 0 }],
        });
      }
    }
  }, [events, isLiveStatus, status]);

  // Cleanup on unmount
  useEffect(() => {
    const timeoutMap = timeoutRefs.current;
    return () => {
      for (const t of timeoutMap.values()) window.clearTimeout(t);
      timeoutMap.clear();
    };
  }, []);

  return null;
}
