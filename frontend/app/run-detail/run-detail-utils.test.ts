import { describe, expect, it } from "vitest";
import { aggregateModelUsage, extractResultContent, inferWorkspacePhase } from "./run-detail-utils";

describe("extractResultContent", () => {
    it("returns string directly", () => {
        expect(extractResultContent("hello")).toBe("hello");
    });

    it("extracts message-like fields from object", () => {
        expect(extractResultContent({ message: "m1" })).toBe("m1");
        expect(extractResultContent({ response: "m2" })).toBe("m2");
        expect(extractResultContent({ content: "m3" })).toBe("m3");
    });

    it("stringifies unknown object shape", () => {
        const out = extractResultContent({ foo: "bar" });
        expect(out).toContain("foo");
    });
});

describe("inferWorkspacePhase", () => {
    it("prefers explicit hydrated projection status", () => {
        expect(inferWorkspacePhase({ projectionStatus: "hydrated", cardCount: 0 })).toBe("hydrated");
    });

    it("prefers explicit empty projection status", () => {
        expect(inferWorkspacePhase({ projectionStatus: "empty", cardCount: 10 })).toBe("empty");
    });

    it("falls back to card count when projection status missing", () => {
        expect(inferWorkspacePhase({ cardCount: 2 })).toBe("hydrated");
        expect(inferWorkspacePhase({ cardCount: 0 })).toBe("empty");
    });
});

describe("aggregateModelUsage", () => {
    it("returns empty list for zero usage", () => {
        expect(aggregateModelUsage([])).toEqual([]);
    });

    it("aggregates single model usage", () => {
        const result = aggregateModelUsage([
            {
                model_used: "gpt-4o-mini",
                provider: "openai",
                total_tokens: 100,
                total_cost_usd: 0.01,
            },
        ]);
        expect(result).toHaveLength(1);
        expect(result[0].model).toBe("gpt-4o-mini");
        expect(result[0].provider).toBe("openai");
        expect(result[0].tokens).toBe(100);
        expect(result[0].cost).toBe(0.01);
        expect(result[0].percentage).toBe(100);
    });

    it("aggregates multi-model breakdown and sorts by cost", () => {
        const result = aggregateModelUsage([
            {
                metadata: {
                    model_breakdown: [
                        { model: "claude-3-5-sonnet", provider: "anthropic", cost_usd: 0.03, tokens: 300, executions: 1 },
                        { model: "gpt-4o-mini", provider: "openai", cost_usd: 0.01, tokens: 100, executions: 2 },
                    ],
                },
            },
        ]);
        expect(result).toHaveLength(2);
        expect(result[0].model).toBe("claude-3-5-sonnet");
        expect(result[0].cost).toBe(0.03);
        expect(result[1].model).toBe("gpt-4o-mini");
        expect(result[1].cost).toBe(0.01);
        expect(result[0].percentage).toBeGreaterThan(result[1].percentage);
    });
});
