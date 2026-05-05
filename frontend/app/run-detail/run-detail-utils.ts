"use client";

export function formatDuration(seconds: number): string {
    if (seconds < 60) {
        return `${seconds.toFixed(1)}s`;
    }
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.round(seconds % 60);
    return `${minutes}m ${remainingSeconds}s`;
}

export function extractResultContent(value: unknown): string {
    if (!value) return "";
    if (typeof value === "string") return value;
    if (typeof value === "object") {
        const record = value as Record<string, unknown>;
        const extracted = record.text || record.message || record.response || record.content || record.result || record.output;
        if (typeof extracted === "string") return extracted;
        try {
            return JSON.stringify(value);
        } catch {
            return "";
        }
    }
    return String(value);
}

export function inferWorkspacePhase(params: {
    projectionStatus?: "hydrated" | "empty";
    cardCount: number;
}): "hydrated" | "empty" {
    if (params.projectionStatus === "hydrated") return "hydrated";
    if (params.projectionStatus === "empty") return "empty";
    return params.cardCount > 0 ? "hydrated" : "empty";
}

type ModelBreakdownEntry = {
    model: string;
    provider?: string;
    executions?: number;
    tokens?: number;
    cost_usd?: number;
    prompt_tokens?: number;
    completion_tokens?: number;
    estimated_executions?: number;
};

type HistoryTaskLike = {
    model_used?: string;
    provider?: string;
    total_tokens?: number;
    total_cost_usd?: number;
    metadata?: {
        model?: string;
        provider?: string;
        model_breakdown?: ModelBreakdownEntry[];
    };
};

export type AggregatedModelUsage = {
    model: string;
    provider: string;
    executions: number;
    tokens: number;
    cost: number;
    inputTokens: number;
    outputTokens: number;
    estimatedExecutions: number;
    percentage: number;
};

export function aggregateModelUsage(tasks: HistoryTaskLike[]): AggregatedModelUsage[] {
    const modelUsage = new Map<string, Omit<AggregatedModelUsage, "percentage">>();
    let totalCost = 0;

    tasks.forEach((task) => {
        const modelBreakdown = task.metadata?.model_breakdown;
        if (modelBreakdown && Array.isArray(modelBreakdown) && modelBreakdown.length > 0) {
            modelBreakdown.forEach((entry) => {
                const provider = entry.provider || "unknown";
                const key = `${entry.model}|${provider}`;
                const existing = modelUsage.get(key);
                const cost = entry.cost_usd || 0;
                const executions = entry.executions || 1;
                const tokens = entry.tokens || 0;
                const promptTokens = entry.prompt_tokens || 0;
                const completionTokens = entry.completion_tokens || 0;
                const estimatedExecutions = entry.estimated_executions || 0;

                if (existing) {
                    existing.executions += executions;
                    existing.tokens += tokens;
                    existing.cost += cost;
                    existing.inputTokens += promptTokens;
                    existing.outputTokens += completionTokens;
                    existing.estimatedExecutions += estimatedExecutions;
                } else {
                    modelUsage.set(key, {
                        model: entry.model,
                        provider,
                        executions,
                        tokens,
                        cost,
                        inputTokens: promptTokens,
                        outputTokens: completionTokens,
                        estimatedExecutions,
                    });
                }
                totalCost += cost;
            });
            return;
        }

        const model = task.model_used || task.metadata?.model;
        if (!model) return;
        const provider = task.provider || task.metadata?.provider || "unknown";
        const key = `${model}|${provider}`;
        const existing = modelUsage.get(key);
        const cost = task.total_cost_usd || 0;
        const tokens = task.total_tokens || 0;
        if (existing) {
            existing.executions += 1;
            existing.tokens += tokens;
            existing.cost += cost;
        } else {
            modelUsage.set(key, {
                model,
                provider,
                executions: 1,
                tokens,
                cost,
                inputTokens: 0,
                outputTokens: 0,
                estimatedExecutions: 0,
            });
        }
        totalCost += cost;
    });

    return Array.from(modelUsage.values())
        .sort((a, b) => b.cost - a.cost || a.model.localeCompare(b.model))
        .map((entry) => ({
            ...entry,
            percentage: totalCost > 0 ? Math.round((entry.cost / totalCost) * 100) : 0,
        }));
}
