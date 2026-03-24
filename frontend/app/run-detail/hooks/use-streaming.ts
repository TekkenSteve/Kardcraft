"use client";

import { useCallback, useEffect } from "react";
import { useDispatch } from "react-redux";
import { useTranslation } from "react-i18next";
import { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { getTask } from "@/lib/kardcraft/api";
import {
    getSessionConversation,
    getSessionTimeline,
    getSessionHistory,
} from "@/lib/kardcraft/session-repository";
import {
    addMessage,
    updateMessageMetadata,
    setStreamError,
    setSelectedAgent,
    setResearchStrategy,
    setMainWorkflowId,
    setStatus,
    setPaused,
    setCancelling,
    setCancelled,
    setRunPhase,
} from "@/lib/features/runSlice";
import { extractResultContent } from "../run-detail-utils";
import { SessionDataBundle, SessionHistoryData } from "../run-detail-types";
import { RunMessage } from "@/lib/features/runSlice";
import { RunEvent } from "@/lib/kardcraft/types";

const isTaskScopedWorkflowId = (value: string | null | undefined): value is string => {
    if (!value) return false;
    const trimmed = value.trim();
    if (!trimmed) return false;
    // Disallow user/session scoped channels in run-detail realtime binding.
    if (trimmed.startsWith("user:") || trimmed.startsWith("session:")) return false;
    return true;
};

export function useStreaming({
    sessionId,
    workflowIdParam,
    searchParams,
    router,
    isNewSession,
    currentTaskId,
    setCurrentTaskId,
    actualSessionId,
    setActualSessionId,
    setSessionData,
    setSessionHistory,
    setIsLoading,
    setError,
    runStatus,
    runMessages,
    runEvents,
    hasInitializedTaskRef,
    startTransition,
    setLoadPhase,
}: {
    sessionId: string | null;
    workflowIdParam: string | null;
    searchParams: URLSearchParams;
    router: AppRouterInstance;
    isNewSession: boolean;
    currentTaskId: string | null;
    setCurrentTaskId: (id: string | null) => void;
    actualSessionId: string | null;
    setActualSessionId: (id: string | null) => void;
    setSessionData: (data: SessionDataBundle | null) => void;
    setSessionHistory: (data: SessionHistoryData) => void;
    setIsLoading: (value: boolean) => void;
    setError: (value: string | null) => void;
    runStatus: "idle" | "running" | "completed" | "failed";
    runMessages: RunMessage[];
    runEvents: RunEvent[];
    hasInitializedTaskRef: React.MutableRefObject<string | null>;
    startTransition: (cb: () => void) => void;
    setLoadPhase: (value: "idle" | "clearing" | "loading" | "hydrated" | "streaming") => void;
}) {
    const dispatch = useDispatch();
    const { t } = useTranslation();

    useEffect(() => {
        const initializeFromTask = async () => {
            if (!workflowIdParam) return;

            if (hasInitializedTaskRef.current === workflowIdParam) {
                return;
            }

            hasInitializedTaskRef.current = workflowIdParam;

            try {
                setIsLoading(true);
                const task = await getTask(workflowIdParam);
                const preferredWorkflowId = isTaskScopedWorkflowId(task.workflow_id)
                    ? task.workflow_id
                    : (isTaskScopedWorkflowId(workflowIdParam) ? workflowIdParam : null);
                if (!preferredWorkflowId) {
                    throw new Error("Invalid workflow identifier for task-scoped streaming");
                }
                const workflowId = preferredWorkflowId;

                setCurrentTaskId(workflowId);
                dispatch(setMainWorkflowId(workflowId));

                let taskContext = task.context;
                if (!taskContext && task.metadata?.task_context) {
                    taskContext = task.metadata.task_context;
                }

                if (taskContext) {
                    const isTemplateTask =
                        task.task_type === "card_template" ||
                        task.mode === "card_template" ||
                        taskContext.template_id !== undefined ||
                        taskContext.force_research === true ||
                        taskContext.force_research === "true";
                    const strategy = taskContext.research_strategy || "quick";

                    dispatch(setSelectedAgent(isTemplateTask ? "card_template" : "normal"));
                    if (isTemplateTask) {
                        dispatch(setResearchStrategy(strategy as "quick" | "standard" | "deep" | "academic"));
                    }
                }

                dispatch(addMessage({
                    id: `user-${workflowIdParam}`,
                    role: "user",
                    content: task.query,
                    timestamp: new Date(task.created_at || Date.now()).toLocaleTimeString(),
                    taskId: workflowId,
                }));

                if (task.status === "TASK_STATUS_RUNNING" || task.status === "TASK_STATUS_QUEUED") {
                    dispatch(addMessage({
                        id: `generating-${workflowId}`,
                        role: "assistant",
                        content: t("runDetail.generating"),
                        timestamp: new Date().toLocaleTimeString(),
                        isGenerating: true,
                        taskId: workflowId,
                    }));
                }

                if (task.session_id) {
                    setActualSessionId(task.session_id);
                    if (!sessionId || sessionId === "new") {
                        const newParams = new URLSearchParams(searchParams.toString());
                        newParams.set("session_id", task.session_id);
                        router.replace(`/run-detail?${newParams.toString()}`);
                    }
                }
            } catch (err) {
                console.error("Failed to fetch task details:", err);
                setError(t("runDetail.taskLoadFailed"));
            } finally {
                setIsLoading(false);
            }
        };

        initializeFromTask();
    }, [workflowIdParam, sessionId, router, searchParams, dispatch, hasInitializedTaskRef, setIsLoading, setCurrentTaskId, setActualSessionId, setError, t]);

    useEffect(() => {
        const effectiveSessionId = actualSessionId || (sessionId !== "new" ? sessionId : null);

        if (runStatus === "completed" && effectiveSessionId) {
            let retryCount = 0;
            const maxRetries = 3;
            const delays = [1500, 3000, 5000];

            const fetchWithRetry = async () => {
                try {
                    const [historyData, conversation, timeline] = await Promise.all([
                        getSessionHistory(effectiveSessionId),
                        getSessionConversation(effectiveSessionId),
                        getSessionTimeline(effectiveSessionId, 200, 0, false),
                    ]);

                    startTransition(() => {
                        setSessionHistory(historyData);
                    });
                    startTransition(() => {
                        setSessionData({ conversation, timeline });
                    });

                    const hasMeaningfulData = historyData?.tasks?.some((task) =>
                        (task.duration_ms || 0) > 0
                    );

                    if (!hasMeaningfulData && retryCount < maxRetries) {
                        retryCount++;
                        setTimeout(fetchWithRetry, delays[retryCount - 1]);
                    }

                } catch {
                    if (retryCount < maxRetries) {
                        retryCount++;
                        setTimeout(fetchWithRetry, delays[retryCount - 1]);
                    }
                }
            };

            const timer = setTimeout(fetchWithRetry, delays[0]);
            return () => clearTimeout(timer);
        }
    }, [runStatus, sessionId, actualSessionId, startTransition, setSessionData, setSessionHistory]);

    const handleTaskCreated = async (newTaskId: string, query: string, workflowId?: string, newSessionId?: string) => {
        const activeWorkflowId = isTaskScopedWorkflowId(workflowId)
            ? workflowId
            : (isTaskScopedWorkflowId(newTaskId) ? newTaskId : null);
        if (!activeWorkflowId) {
            setError(t("runDetail.taskLoadFailed"));
            return;
        }
        setCurrentTaskId(activeWorkflowId);
        dispatch(setMainWorkflowId(activeWorkflowId));
        dispatch(setStatus("running"));
        dispatch(setCancelling({ value: false }));
        dispatch(setCancelled({ value: false }));
        dispatch(setPaused({ paused: false }));

        dispatch(addMessage({
            id: `user-${newTaskId}`,
            role: "user",
            content: query,
            timestamp: new Date().toLocaleTimeString(),
            taskId: activeWorkflowId,
        }));

        dispatch(addMessage({
            id: `generating-${activeWorkflowId}`,
            role: "assistant",
            content: t("runDetail.generating"),
            timestamp: new Date().toLocaleTimeString(),
            isGenerating: true,
            taskId: activeWorkflowId,
        }));
        setLoadPhase("streaming");
        dispatch(setRunPhase({ next: "streaming" }));

        if (newSessionId) {
            setActualSessionId(newSessionId);
            const newParams = new URLSearchParams(searchParams.toString());
            newParams.set("session_id", newSessionId);
            router.replace(`/run-detail?${newParams.toString()}`);
            return;
        }

        if (isNewSession) {
            try {
                const taskDetails = await getTask(activeWorkflowId);
                if (taskDetails.session_id) {
                    setActualSessionId(taskDetails.session_id);
                    const newParams = new URLSearchParams(searchParams.toString());
                    newParams.set("session_id", taskDetails.session_id);
                    router.replace(`/run-detail?${newParams.toString()}`);
                }
            } catch (err) {
                console.warn("Failed to refresh session ID after task creation:", err);
            }
        }
    };

    const fetchFinalOutput = useCallback(async () => {
        if (!currentTaskId) {
            return;
        }
        try {
            const task = await getTask(currentTaskId);
            if (task.status !== "TASK_STATUS_COMPLETED") {
                if (task.status === "TASK_STATUS_RUNNING" || task.status === "TASK_STATUS_QUEUED") {
                    dispatch(setStatus("running"));
                    return;
                } else if (task.status === "TASK_STATUS_FAILED" || task.status === "TASK_STATUS_CANCELLED") {
                    dispatch(setStatus("failed"));
                    if (task.status === "TASK_STATUS_CANCELLED") {
                        dispatch(setCancelled({ value: true, message: t("runDetail.cancelledMessage") }));
                    } else {
                        dispatch(setStreamError(task.error_message || t("runDetail.taskFailed")));
                    }
                    return;
                }
            }

            const rawResult = task.final_output || task.result;
            if (!rawResult) {
                return;
            }

            const resultContent = extractResultContent(rawResult);
            if (!resultContent) return;

            const hasExistingAssistantMessage = runMessages.some((m) => {
                if (m.role !== "assistant" || m.isStreaming || m.isGenerating) return false;
                if (!m.content || m.content.length === 0) return false;
                return m.taskId === currentTaskId;
            });

            if (hasExistingAssistantMessage) {
                const existingMsg = runMessages.find(
                    (m) =>
                        m.role === "assistant" &&
                        !m.isStreaming &&
                        !m.isGenerating &&
                        m.taskId === currentTaskId
                );
                if (
                    task.metadata?.citations &&
                    existingMsg?.taskId &&
                    (!existingMsg?.metadata?.citations || existingMsg.metadata.citations.length === 0)
                ) {
                    dispatch(
                        updateMessageMetadata({
                            taskId: existingMsg.taskId,
                            metadata: { citations: task.metadata.citations },
                        })
                    );
                }
                return;
            }

            const lowerResult = resultContent.toLowerCase().trim();
            const isStatusMessage =
                lowerResult === 'task completed' ||
                lowerResult === 'task done' ||
                lowerResult === 'done' ||
                lowerResult === 'completed' ||
                lowerResult === 'success' ||
                (lowerResult === 'successfully' && resultContent.length < 20);

            if (isStatusMessage) {
                dispatch(setStreamError(t("runDetail.finalOutputMissing")));
                return;
            }

            dispatch(addMessage({
                id: `assistant-final-${currentTaskId}`,
                role: "assistant",
                content: resultContent,
                timestamp: new Date().toLocaleTimeString(),
                metadata: task.metadata,
                taskId: currentTaskId,
            }));

            dispatch(setStreamError(null));
        } catch {
            dispatch(setStreamError(t("runDetail.finalOutputFailed")));
        }
    }, [currentTaskId, dispatch, runMessages, t]);

    const handleFetchFinalOutputClick = () => {
        fetchFinalOutput();
    };

    useEffect(() => {
        const fetchTaskResult = async () => {
            if (runStatus === "completed" && currentTaskId) {
                const hasLiveEventsForTask = runEvents.some(
                    (event) => event.workflow_id === currentTaskId && !event.isHistorical
                );
                const hasGeneratingPlaceholder = runMessages.some(
                    (message) => message.isGenerating && message.taskId === currentTaskId
                );

                // Only fetch final output for actively streamed tasks in this page lifecycle.
                // For historical sessions, conversation API is the source of truth.
                if (!hasLiveEventsForTask && !hasGeneratingPlaceholder) {
                    return;
                }
                await fetchFinalOutput();
            }
        };

        fetchTaskResult();
    }, [runStatus, currentTaskId, fetchFinalOutput, runEvents, runMessages]);

    useEffect(() => {
        if (runStatus === "running") {
            setLoadPhase("streaming");
            dispatch(setRunPhase({ next: "streaming" }));
            return;
        }
        if (runStatus === "completed" || runStatus === "failed") {
            setLoadPhase("hydrated");
            dispatch(setRunPhase({ next: "hydrated" }));
        }
    }, [runStatus, setLoadPhase, dispatch]);

    const handleRetryStream = () => {
        dispatch(setStreamError(null));
    };

    return {
        handleTaskCreated,
        handleFetchFinalOutputClick,
        handleRetryStream,
    };
}
