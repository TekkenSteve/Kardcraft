"use client";

import { StatePanel } from "@/components/state-panel";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { SessionHistoryResponseRecord } from "@/lib/kardcraft/session-schemas";
import { useTranslation } from "react-i18next";
import { useRunDetailData } from "./run-detail-hooks";
import { aggregateModelUsage, formatDuration } from "./run-detail-utils";

export function SummaryPanel() {
    const { t } = useTranslation();
    const {
        sessionHistory,
        sessionId,
        currentWorkflowId,
        runStatus,
    } = useRunDetailData();

    const tasks: SessionHistoryResponseRecord["tasks"] = sessionHistory?.tasks || [];
    const hasTokenData = tasks.some((task) => typeof task.total_tokens === "number");
    const hasCostData = tasks.some((task) => typeof task.total_cost_usd === "number");
    const usagePendingCount = tasks.filter((task) => task.usage_projection_status === "pending" || task.usage_projection_status === "partial").length;
    const usageInvalidCount = tasks.filter((task) => task.usage_projection_status === "invalid").length;

    return (
        <div className="max-w-4xl mx-auto space-y-4 overflow-hidden">
            <div>
                <h2 className="text-xl font-semibold">{t("runDetail.summaryTitle")}</h2>
                <p className="text-sm text-muted-foreground">{t("runDetail.summarySubtitle")}</p>
                {usagePendingCount > 0 && (
                    <p className="text-xs text-amber-700 dark:text-amber-400 mt-1">{t("runDetail.usageProcessing", { count: usagePendingCount })}</p>
                )}
                {usageInvalidCount > 0 && (
                    <p className="text-xs text-red-700 dark:text-red-400 mt-1">{t("runDetail.usageInvalid", { count: usageInvalidCount })}</p>
                )}
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <Card className="p-3">
                    <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{t("runDetail.totalTurns")}</div>
                    <div className="text-xl sm:text-2xl font-semibold mt-1">
                        {tasks.length}
                    </div>
                </Card>
                <Card className="p-3">
                    <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{t("runDetail.totalCosts")}</div>
                    <div className="text-xl sm:text-2xl font-semibold mt-1">
                        {hasCostData ? (
                            `$${tasks.reduce((sum, task) => sum + (task.total_cost_usd || 0), 0).toFixed(4)}`
                        ) : (
                            "—"
                        )}
                    </div>
                </Card>
                <Card className="p-3">
                    <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{t("runDetail.totalTokens")}</div>
                    <div className="text-xl sm:text-2xl font-semibold mt-1">
                        {hasTokenData ? (
                            tasks.reduce((sum, task) => sum + (task.total_tokens || 0), 0).toLocaleString()
                        ) : (
                            "—"
                        )}
                    </div>
                </Card>
                <Card className="p-3">
                    <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{t("runDetail.totalTime")}</div>
                    <div className="text-xl sm:text-2xl font-semibold mt-1">
                        {formatDuration(tasks.reduce((sum, task) => sum + (task.duration_ms || 0), 0) / 1000)}
                    </div>
                </Card>
            </div>

            {tasks.length === 0 && (
                <StatePanel
                    title={t("runDetail.summaryEmptyTitle")}
                    description={t("runDetail.summaryEmpty")}
                />
            )}

            {tasks.length > 0 && hasTokenData && (
                <Card className="p-3 sm:p-4 overflow-hidden">
                    <h3 className="text-base font-semibold mb-3">{t("runDetail.tokenUsageByTurn")}</h3>
                    <div className="space-y-2">
                        {tasks.map((task, index: number) => (
                            <div key={task.task_id} className="py-2 border-b last:border-b-0">
                                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                                    <div className="flex-1 min-w-0">
                                        <div className="text-xs font-medium truncate">{t("runDetail.turnLabel", { index: index + 1 })}</div>
                                        <div className="text-xs text-muted-foreground truncate">{task.query}</div>
                                        {task.usage_projection_status && (
                                            <div className="text-[10px] text-muted-foreground mt-0.5 truncate">
                                                {t("runDetail.usageStatus")}: {task.usage_projection_status}
                                                {task.usage_projection_reason ? ` (${task.usage_projection_reason})` : ""}
                                            </div>
                                        )}
                                        {(task.model_used || task.metadata?.model) && (
                                            <div className="text-xs text-muted-foreground mt-0.5 truncate">
                                                {task.model_used || task.metadata?.model}
                                                {(task.provider || task.metadata?.provider) && ` (${task.provider || task.metadata?.provider})`}
                                            </div>
                                        )}
                                    </div>
                                    <div className="flex items-center gap-3 sm:gap-4 sm:ml-4 flex-shrink-0">
                                        <div className="text-left sm:text-right">
                                            <div className="text-sm font-medium">{(task.total_tokens || 0).toLocaleString()}</div>
                                            <div className="text-xs text-muted-foreground">{t("runDetail.tokensLabel")}</div>
                                        </div>
                                        <div className="text-left sm:text-right">
                                            <div className="text-sm font-medium">${(task.total_cost_usd || 0).toFixed(4)}</div>
                                            <div className="text-xs text-muted-foreground">{t("runDetail.costLabel")}</div>
                                        </div>
                                        <div className="text-left sm:text-right">
                                            <div className="text-sm font-medium">{formatDuration((task.duration_ms || 0) / 1000)}</div>
                                            <div className="text-xs text-muted-foreground">{t("runDetail.timeLabel")}</div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </Card>
            )}

            {tasks.length > 0 && hasCostData && (() => {
                const modelsWithPercentage = aggregateModelUsage(tasks);
                const hasDetailedData = tasks.some(
                    (task) =>
                        Array.isArray(task.metadata?.model_breakdown) &&
                        task.metadata?.model_breakdown.length > 0
                );
                const hasEstimatedData = tasks.some(
                    (task) =>
                        typeof task.metadata?.usage_quality?.estimated_ratio === "number" &&
                        task.metadata?.usage_quality?.estimated_ratio > 0
                );

                const barColors = [
                    'bg-blue-500',
                    'bg-emerald-500',
                    'bg-amber-500',
                    'bg-purple-500',
                    'bg-rose-500',
                    'bg-cyan-500',
                ];

                return modelsWithPercentage.length > 0 ? (
                    <Card className="p-3 sm:p-4 overflow-hidden">
                        <div className="flex items-center justify-between mb-3">
                            <h3 className="text-base font-semibold">{t("runDetail.modelsUsed")}</h3>
                            <div className="flex items-center gap-1">
                                {hasDetailedData && (
                                    <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                                        {t("runDetail.detailed")}
                                    </span>
                                )}
                                {hasEstimatedData && (
                                    <span className="text-[10px] text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded border border-amber-200">
                                        estimated
                                    </span>
                                )}
                            </div>
                        </div>
                        <div className="space-y-3">
                            {modelsWithPercentage.map((usage, index) => (
                                <div key={`${usage.model}-${usage.provider}`} className="space-y-1.5">
                                    <div className="flex items-center justify-between text-xs">
                                        <div className="flex items-center gap-2 min-w-0">
                                            <div
                                                className={`size-2 rounded-full flex-shrink-0 ${barColors[index % barColors.length]}`}
                                            />
                                            <span className="font-medium truncate">{usage.model}</span>
                                            <span className="text-muted-foreground text-[10px] flex-shrink-0">
                                                {usage.provider}
                                            </span>
                                        </div>
                                        <span className="text-muted-foreground flex-shrink-0 ml-2">
                                            {usage.percentage}%
                                        </span>
                                    </div>
                                    <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                                        <div
                                            className={`h-full rounded-full transition-all duration-500 ${barColors[index % barColors.length]}`}
                                            style={{ width: `${Math.max(usage.percentage, 2)}%` }}
                                        />
                                    </div>
                                    <div className="flex items-center gap-3 text-[10px] text-muted-foreground pl-4">
                                        <span>{usage.executions} {usage.executions === 1 ? t("runDetail.call") : t("runDetail.calls")}</span>
                                        {usage.inputTokens > 0 && usage.outputTokens > 0 ? (
                                            <span className="flex items-center gap-1">
                                                <span className="text-blue-500/70">↓{usage.inputTokens.toLocaleString()}</span>
                                                <span>/</span>
                                                <span className="text-emerald-500/70">↑{usage.outputTokens.toLocaleString()}</span>
                                            </span>
                                        ) : (
                                            <span>{usage.tokens.toLocaleString()} {t("runDetail.tokensLabel")}</span>
                                        )}
                                        <span className="font-medium text-foreground">${usage.cost.toFixed(4)}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </Card>
                ) : null;
            })()}

            {sessionHistory?.tasks && sessionHistory.tasks.length > 0 && (() => {
                const allAgents = new Set<string>();
                sessionHistory.tasks.forEach((task) => {
                    const agents = task.metadata?.agents_involved;
                    if (!Array.isArray(agents)) return;
                    agents
                        .filter((agent): agent is string => typeof agent === "string" && agent.trim().length > 0)
                        .forEach((agent) => allAgents.add(agent));
                });
                return allAgents.size > 0 ? (
                    <Card className="p-3 sm:p-4">
                        <h3 className="text-base font-semibold mb-3">{t("runDetail.agentsInvolved")}</h3>
                        <div className="flex flex-wrap gap-2">
                            {Array.from(allAgents).map(agent => (
                                <Badge key={agent} variant="secondary" className="text-xs truncate max-w-full">
                                    {agent}
                                </Badge>
                            ))}
                        </div>
                    </Card>
                ) : null;
            })()}

            {sessionHistory?.tasks && sessionHistory.tasks.length > 0 && (
                <Card className="p-3 sm:p-4">
                    <h3 className="text-base font-semibold mb-3">{t("runDetail.averageMetrics")}</h3>
                    <div className="grid grid-cols-2 gap-3 sm:gap-4">
                        <div>
                            <div className="text-xs text-muted-foreground">{t("runDetail.avgTokensPerTurn")}</div>
                            <div className="text-lg font-semibold mt-1">
                                {Math.round(
                                    sessionHistory.tasks.reduce((sum, task) => sum + (task.total_tokens || 0), 0) / sessionHistory.tasks.length
                                ).toLocaleString()}
                            </div>
                        </div>
                        <div>
                            <div className="text-xs text-muted-foreground">{t("runDetail.avgTimePerTurn")}</div>
                            <div className="text-lg font-semibold mt-1">
                                {formatDuration(
                                    sessionHistory.tasks.reduce((sum, task) => sum + (task.duration_ms || 0), 0) /
                                    sessionHistory.tasks.length / 1000
                                )}
                            </div>
                        </div>
                    </div>
                </Card>
            )}

            <Card className="p-3 sm:p-4 overflow-hidden">
                <h3 className="text-base font-semibold mb-3">{t("runDetail.sessionInformation")}</h3>
                <div className="space-y-2 text-xs">
                    <div className="flex justify-between items-center gap-2">
                        <span className="text-muted-foreground shrink-0">{t("runDetail.sessionId")}</span>
                        <span className="font-mono text-xs truncate min-w-0">{sessionId}</span>
                    </div>
                    {currentWorkflowId && (
                        <div className="flex justify-between items-center gap-2">
                            <span className="text-muted-foreground shrink-0">{t("runDetail.currentTaskId")}</span>
                            <span className="font-mono text-xs truncate min-w-0">{currentWorkflowId}</span>
                        </div>
                    )}
                    <div className="flex justify-between items-center">
                        <span className="text-muted-foreground">{t("runDetail.status")}</span>
                        <Badge
                            variant="outline"
                            className={`text-xs ${runStatus === "completed"
                                ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                : runStatus === "running"
                                    ? "bg-blue-50 text-blue-700 border-blue-200"
                                    : runStatus === "pausing"
                                    ? "bg-blue-50 text-blue-700 border-blue-200"
                                    : runStatus === "resuming"
                                    ? "bg-blue-50 text-blue-700 border-blue-200"
                                    : runStatus === "paused"
                                        ? "bg-amber-50 text-amber-700 border-amber-200"
                                        : runStatus === "cancelling"
                                            ? "bg-orange-50 text-orange-700 border-orange-200"
                                            : runStatus === "cancelled"
                                                ? "bg-yellow-50 text-yellow-700 border-yellow-200"
                                    : runStatus === "failed"
                                        ? "bg-red-50 text-red-700 border-red-200"
                                        : ""
                                }`}
                        >
                            {runStatus}
                        </Badge>
                    </div>
                </div>
            </Card>
        </div>
    );
}
