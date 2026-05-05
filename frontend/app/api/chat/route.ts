import { NextRequest } from "next/server";

type ChatRequestBody = {
  workflowId?: string;
};

const API_BASE_PATH = process.env.NEXT_PUBLIC_API_BASE_PATH || "";

function buildApiUrl(request: NextRequest, path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const requestOrigin = request.nextUrl.origin;

  const base = API_BASE_PATH.trim();
  if (!base) {
    return new URL(normalizedPath, requestOrigin).toString();
  }

  if (/^https?:\/\//i.test(base)) {
    return new URL(normalizedPath, base).toString();
  }

  return new URL(`${base.replace(/\/$/, "")}${normalizedPath}`, requestOrigin).toString();
}

function toTextDelta(payload: unknown): string {
  if (!payload || typeof payload !== "object") return "";
  const record = payload as Record<string, unknown>;
  const direct = record.delta ?? record.text ?? record.content;
  if (typeof direct === "string") return direct;
  const nested = record.payload;
  if (nested && typeof nested === "object") {
    const nestedRecord = nested as Record<string, unknown>;
    const nestedDirect = nestedRecord.delta ?? nestedRecord.text ?? nestedRecord.content;
    if (typeof nestedDirect === "string") return nestedDirect;
  }
  return "";
}

function toCompletedText(payload: unknown): string {
  if (!payload || typeof payload !== "object") return "";
  const record = payload as Record<string, unknown>;
  const direct = record.response ?? record.content ?? record.text;
  if (typeof direct === "string") return direct;
  const nested = record.payload;
  if (nested && typeof nested === "object") {
    const nestedRecord = nested as Record<string, unknown>;
    const nestedDirect = nestedRecord.response ?? nestedRecord.content ?? nestedRecord.text;
    if (typeof nestedDirect === "string") return nestedDirect;
  }
  return "";
}

function toMessageText(payload: unknown): string {
  if (!payload || typeof payload !== "object") return "";
  const record = payload as Record<string, unknown>;
  const direct = record.message ?? record.text ?? record.content ?? record.response;
  if (typeof direct === "string") return direct;
  const nested = record.payload;
  if (nested && typeof nested === "object") {
    const nestedRecord = nested as Record<string, unknown>;
    const nestedDirect = nestedRecord.message ?? nestedRecord.text ?? nestedRecord.content ?? nestedRecord.response;
    if (typeof nestedDirect === "string") return nestedDirect;
  }
  return "";
}

function isTerminalEvent(eventType: string): boolean {
  return (
    eventType === "WORKFLOW_COMPLETED" ||
    eventType === "workflow.completed" ||
    eventType === "WORKFLOW_FAILED" ||
    eventType === "workflow.failed" ||
    eventType === "WORKFLOW_CANCELLED" ||
    eventType === "workflow.cancelled" ||
    eventType === "done" ||
    eventType === "STREAM_END"
  );
}

function computeCompletedTail(accumulated: string, completed: string): string {
  if (!completed) return "";
  if (!accumulated) return completed;
  if (completed.startsWith(accumulated)) {
    return completed.slice(accumulated.length);
  }
  return completed;
}

export async function POST(request: NextRequest): Promise<Response> {
  const body = (await request.json().catch(() => ({}))) as ChatRequestBody;
  const workflowId = typeof body.workflowId === "string" ? body.workflowId.trim() : "";

  if (!workflowId) {
    return new Response("workflowId is required", { status: 400 });
  }

  const cookie = request.headers.get("cookie") || "";
  const upstream = await fetch(
    buildApiUrl(request, `/api/v1/stream/sse?workflow_id=${encodeURIComponent(workflowId)}`),
    {
      method: "GET",
      headers: {
        cookie,
        accept: "text/event-stream",
      },
      cache: "no-store",
    }
  );

  if (!upstream.ok || !upstream.body) {
    const message = await upstream.text().catch(() => "Failed to open stream");
    return new Response(message || "Failed to open stream", { status: upstream.status || 502 });
  }

  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  const reader = upstream.body.getReader();

  let buffer = "";
  let streamedAssistantText = "";

  const stream = new ReadableStream<Uint8Array>({
    async pull(controller) {
      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          controller.close();
          return;
        }

        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";

        for (const frame of frames) {
          const dataLine = frame
            .split("\n")
            .find((line) => line.startsWith("data:"));
          if (!dataLine) continue;

          const raw = dataLine.slice(5).trim();
          if (!raw || raw === "[DONE]") continue;

          let parsed: Record<string, unknown>;
          try {
            parsed = JSON.parse(raw) as Record<string, unknown>;
          } catch {
            continue;
          }

          const eventType =
            (typeof parsed.event_type === "string" && parsed.event_type) ||
            (typeof parsed.type === "string" && parsed.type) ||
            "";

          if (eventType === "thread.message.delta") {
            const delta = toTextDelta(parsed.payload);
            if (delta) {
              streamedAssistantText += delta;
              controller.enqueue(encoder.encode(delta));
            }
            continue;
          }

          if (eventType === "LLM_PARTIAL") {
            const delta = toTextDelta(parsed.payload);
            if (delta) {
              streamedAssistantText += delta;
              controller.enqueue(encoder.encode(delta));
            }
            continue;
          }

          if (eventType === "thread.message.completed") {
            const completed = toCompletedText(parsed.payload);
            const tail = computeCompletedTail(streamedAssistantText, completed);
            if (tail) {
              streamedAssistantText += tail;
              controller.enqueue(encoder.encode(tail));
            }
            continue;
          }

          if (eventType === "LLM_OUTPUT") {
            const completed = toCompletedText(parsed.payload) || toMessageText(parsed.payload);
            const tail = computeCompletedTail(streamedAssistantText, completed);
            if (tail) {
              streamedAssistantText += tail;
              controller.enqueue(encoder.encode(tail));
            }
            continue;
          }

          if (eventType === "WORKFLOW_COMPLETED" || eventType === "workflow.completed") {
            const completed = toCompletedText(parsed.payload) || toMessageText(parsed.payload);
            const tail = computeCompletedTail(streamedAssistantText, completed);
            if (tail) {
              streamedAssistantText += tail;
              controller.enqueue(encoder.encode(tail));
            }
            controller.close();
            await reader.cancel();
            return;
          }

          if (isTerminalEvent(eventType)) {
            controller.close();
            await reader.cancel();
            return;
          }
        }
      }
    },
    async cancel() {
      await reader.cancel();
    },
  });

  return new Response(stream, {
    status: 200,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
      Connection: "keep-alive",
    },
  });
}

export const __test__ = {
  computeCompletedTail,
  toTextDelta,
  toCompletedText,
  toMessageText,
};
