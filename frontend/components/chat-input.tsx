"use client";

import { FileUpload, FileUploadHandle } from "@/components/file-upload";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";
import { getSessionWorkspace } from "@/lib/kardcraft/session-repository";
import { DEFAULT_TEMPLATE_PREFLIGHT } from "@/lib/run/types";
import { useRunCommands } from "@/lib/run/system";
import { FileUploadAPI } from "@/lib/file-upload/api";
import { UploadedFile } from "@/lib/file-upload/types";
import {
    CardTemplate,
    getTask,
    getTemplateRequiredFields,
    importCardTemplate,
    listCardTemplates,
    precheckCardTemplate,
    setUserTemplatePreference,
    submitTask,
    validateCardTemplate,
} from "@/lib/kardcraft/api";
import { cn } from "@/lib/utils";
import { ChevronDown, LayoutTemplate, Loader2, Paperclip, Pause, Play, Save, Send, Sparkles, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export type AgentSelection = "normal" | "card_template";
export type ResearchStrategy = "quick" | "standard" | "deep" | "academic";

interface ChatInputProps {
    sessionId?: string;
    disabled?: boolean;
    isTaskComplete?: boolean;
    selectedAgent?: AgentSelection;
    onSelectedAgentChange?: (agent: AgentSelection) => void;
    initialResearchStrategy?: ResearchStrategy;
    onTaskCreated: (
        workflowId: string,
        query: string,
        newSessionId?: string,
        attachments?: Array<{fileId: string; filename: string; size: number; mimeType: string}>,
        runId?: string,
    ) => void;
    currentWorkflowId?: string | null;
    /** Use centered textarea layout for empty sessions */
    variant?: "default" | "centered";
    /** Task control props */
    isTaskRunning?: boolean;
    isPaused?: boolean;
    isPauseLoading?: boolean;
    isResumeLoading?: boolean;
    showPause?: boolean;
    showResume?: boolean;
    showCancel?: boolean;
    canControlTask?: boolean;
    isCancelling?: boolean;
    onPause?: () => void;
    onResume?: () => void;
    onCancel?: () => void;
    /** File upload props */
    enableFileUpload?: boolean;
    maxFiles?: number;
    maxFileSize?: number;
    uploadedFiles?: UploadedFile[];
    onUploadedFilesChange?: (files: UploadedFile[]) => void;
}

export function ChatInput({
    sessionId,
    disabled,
    selectedAgent = "normal",
    onSelectedAgentChange,
    initialResearchStrategy = "quick",
    onTaskCreated,
    currentWorkflowId = null,
    variant = "default",
    isTaskRunning = false,
    isPaused = false,
    isPauseLoading = false,
    isResumeLoading = false,
    showPause,
    showResume,
    showCancel,
    canControlTask = true,
    isCancelling = false,
    onPause,
    onResume,
    onCancel,
    enableFileUpload = true,
    maxFiles = 5,
    maxFileSize = 50 * 1024 * 1024, // 50MB
    uploadedFiles: uploadedFilesProp,
    onUploadedFilesChange,
}: ChatInputProps) {
    const { t } = useTranslation();
    const [query, setQuery] = useState("");
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isFilePanelOpen, setIsFilePanelOpen] = useState(false);
    const [localUploadedFiles, setLocalUploadedFiles] = useState<UploadedFile[]>([]);
    const [templates, setTemplates] = useState<CardTemplate[]>([]);
    const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");
    const [selectedTemplateVersion, setSelectedTemplateVersion] = useState<number | undefined>(undefined);
    const [isTemplatesLoading, setIsTemplatesLoading] = useState(true);
    const [isSavingTemplatePref, setIsSavingTemplatePref] = useState(false);
    const [isSavingFromTask, setIsSavingFromTask] = useState(false);
    const [allowAutoFocus, setAllowAutoFocus] = useState(false);
    const fileUploadRef = useRef<FileUploadHandle>(null);
    const filePanelRef = useRef<HTMLDivElement>(null);
    const chatInputRootRef = useRef<HTMLDivElement>(null);
    const commands = useRunCommands();
    const uploadAPI = new FileUploadAPI();
    const uploadedFiles = uploadedFilesProp ?? localUploadedFiles;
    const setUploadedFiles = onUploadedFilesChange ?? setLocalUploadedFiles;
    const shouldShowResume = showResume ?? isPaused;
    const shouldShowPause = showPause ?? (isTaskRunning && !shouldShowResume);
    const shouldShowCancel = showCancel ?? isTaskRunning;
    useEffect(() => {
        setAllowAutoFocus(!window.matchMedia("(pointer: coarse)").matches);
    }, []);
    
    // Use ref for composition state to avoid race conditions with state updates
    // This is more reliable than state for IME handling
    const isComposingRef = useRef(false);

    void initialResearchStrategy;

    useEffect(() => {
        if (!isFilePanelOpen) return;
        const onPointerDown = (event: MouseEvent) => {
            const target = event.target as Node | null;
            if (!target) return;
            if (filePanelRef.current?.contains(target)) return;
            setIsFilePanelOpen(false);
        };
        document.addEventListener("mousedown", onPointerDown);
        return () => {
            document.removeEventListener("mousedown", onPointerDown);
        };
    }, [isFilePanelOpen]);

    useEffect(() => {
        let mounted = true;
        const loadTemplates = async () => {
            setIsTemplatesLoading(true);
            try {
                const data = await listCardTemplates();
                if (!mounted) return;
                const nextTemplates = Array.isArray(data.templates) ? data.templates : [];
                setTemplates(nextTemplates);

                const targetTemplateId =
                    data.user_default_template_id ||
                    "";

                const selectedTemplate = nextTemplates.find((item) => item.template_id === targetTemplateId);
                setSelectedTemplateId(targetTemplateId);
                setSelectedTemplateVersion(
                    data.user_default_template_version ??
                    selectedTemplate?.latest_version ??
                    undefined
                );
            } catch {
                if (!mounted) return;
                setTemplates([]);
                setSelectedTemplateId("");
                setSelectedTemplateVersion(undefined);
            } finally {
                if (mounted) {
                    setIsTemplatesLoading(false);
                }
            }
        };

        void loadTemplates();
        return () => {
            mounted = false;
        };
    }, []);

    const runTemplatePreflight = async (templateId: string, templateVersion?: number) => {
        commands.setTemplatePreflight(sessionId ?? null, {
            status: "running",
            templateId,
            templateVersion: templateVersion ?? null,
            questionTypes: [],
            cardCount: null,
            checkedAt: new Date().toISOString(),
            message: "Running template precheck...",
        });
        try {
            const validation = await validateCardTemplate({
                template_id: templateId,
                version: templateVersion,
            });
            if (!validation.valid || !validation.validation?.ok) {
                const firstError = validation.validation?.errors?.[0]?.message;
                throw new Error(firstError || "Selected template is invalid. Please fix or switch template.");
            }
            const nextQuestionTypes = Array.isArray(validation.available_profiles)
                ? validation.available_profiles
                    .map((item) => String(item || "").trim())
                    .filter((item, index, arr) => item.length > 0 && arr.indexOf(item) === index)
                : [];

            const requiredFields = await getTemplateRequiredFields({
                template_id: templateId,
                version: templateVersion,
            });
            const sampleFields: Record<string, string> = {};
            for (const name of requiredFields.field_names || []) {
                sampleFields[name] = `${name} sample value`;
            }

            const precheck = await precheckCardTemplate({
                template_id: templateId,
                version: templateVersion,
                sample_fields: sampleFields,
            });
            if (precheck.card_count <= 0 || precheck.would_generate_empty) {
                throw new Error("Selected template precheck failed (would generate empty cards). Please switch or fix template.");
            }
            commands.setTemplatePreflight(sessionId ?? null, {
                status: "passed",
                templateId,
                templateVersion: templateVersion ?? null,
                questionTypes: nextQuestionTypes,
                cardCount: precheck.card_count ?? 0,
                checkedAt: new Date().toISOString(),
                message: `Precheck passed (${precheck.card_count} sample cards).`,
            });
            return {
                precheck,
                questionTypes: nextQuestionTypes,
            };
        } catch (error) {
            commands.setTemplatePreflight(sessionId ?? null, {
                status: "failed",
                templateId,
                templateVersion: templateVersion ?? null,
                questionTypes: [],
                cardCount: null,
                checkedAt: new Date().toISOString(),
                message: error instanceof Error ? error.message : "Template precheck failed.",
            });
            throw error;
        }
    };

    const handleSubmit = async (event?: { preventDefault?: () => void }) => {
        event?.preventDefault?.();

        if (!query.trim()) {
            return;
        }
        if (selectedAgent === "normal" && !selectedTemplateId) {
            setError("Please select a card template before starting card generation.");
            return;
        }

        setIsSubmitting(true);
        setError(null);

        try {
            let selectedProfileForSubmit = "";
            if (selectedAgent !== "normal") {
                commands.clearTemplatePreflight(sessionId ?? null);
            }
            if (selectedAgent === "normal" && selectedTemplateId) {
                const preflight = await runTemplatePreflight(selectedTemplateId, selectedTemplateVersion);
                if (sessionId) {
                    try {
                        const workspace = await getSessionWorkspace(sessionId);
                        selectedProfileForSubmit = String(workspace.selected_question_type || "").trim();
                    } catch {
                        selectedProfileForSubmit = "";
                    }
                }
                if (!selectedProfileForSubmit) {
                    selectedProfileForSubmit = String((preflight.questionTypes || [])[0] || "").trim();
                }
            }

            const context: Record<string, unknown> = {};
            let fileIdsToSubmit = uploadedFiles
                .filter((file) => file.status === "uploaded" && !!file.serverFileId)
                .map((file) => file.serverFileId as string);

            context.render_target = "anki";
            if (selectedTemplateId) {
                context.template_id = selectedTemplateId;
            }
            if (selectedTemplateId && selectedTemplateVersion !== undefined) {
                context.template_version = selectedTemplateVersion;
            }
            if (selectedTemplateId && selectedProfileForSubmit) {
                context.template_profile = selectedProfileForSubmit;
            }

            const taskType = selectedAgent === "card_template" ? "card_template" : "main";

            const uploadingFiles = uploadedFiles.filter((file) => file.status === "uploading");
            if (uploadingFiles.length > 0) {
                throw new Error(t("chat.uploadingFiles"));
            }

            const failedFiles = uploadedFiles.filter((file) => file.status === "error");
            if (failedFiles.length > 0) {
                throw new Error(t("chat.failedFiles"));
            }

            const pendingFiles = uploadedFiles.filter((file) => file.status === "pending");
            if (pendingFiles.length > 0) {
                const newlyUploadedFileIds = await fileUploadRef.current?.uploadPendingFiles() ?? [];
                if (newlyUploadedFileIds.length > 0) {
                    fileIdsToSubmit = Array.from(new Set([...fileIdsToSubmit, ...newlyUploadedFileIds]));
                }
            }

            if (uploadedFiles.length > 0 && fileIdsToSubmit.length === 0) {
                throw new Error("检测到已选择文件，但文件上传未成功。请在附件面板查看错误并重试上传。");
            }

            if (fileIdsToSubmit.length > 0) {
                console.info("[DIAG-1] before submitTaskWithFiles", {
                    currentWorkflowId,
                    sessionId,
                    query: query.trim(),
                });
                const attachments = uploadedFiles
                    .filter((file) => file.status === "uploaded" && !!file.serverFileId)
                    .map((file) => ({
                        file_id: file.serverFileId as string,
                        filename: file.name,
                        size: file.size,
                        mime_type: file.type,
                    }));

                // Use the new API for tasks with files
                const response = await uploadAPI.submitTaskWithFiles({
                    query: query.trim(),
                    task_type: taskType,
                    session_id: sessionId,
                    file_ids: fileIdsToSubmit,
                    attachments,
                    template_id: selectedTemplateId || undefined,
                    context: Object.keys(context).length ? context : undefined,
                });

                console.log("[ChatInput] Task with files created, response:", response);
                console.info("[DIAG-1] submitTaskWithFiles response", {
                    workflowId: response.workflow_id,
                    runId: response.run_id ?? null,
                    sessionId: response.session_id ?? null,
                });

                setQuery("");
                setUploadedFiles([]);
                setIsFilePanelOpen(false);
                fileUploadRef.current?.clearFiles();

                onTaskCreated(
                    response.workflow_id,
                    query.trim(),
                    response.session_id,
                    attachments.map((item) => ({
                        fileId: item.file_id,
                        filename: item.filename,
                        size: item.size,
                        mimeType: item.mime_type,
                    })),
                    response.run_id,
                );
            } else {
                // Use the existing API for tasks without files
                console.info("[DIAG-1] before submitTask", {
                    currentWorkflowId,
                    sessionId,
                    query: query.trim(),
                });
                const response = await submitTask({
                    query: query.trim(),
                    task_type: taskType,
                    session_id: sessionId,
                    template_id: selectedTemplateId || undefined,
                    context: Object.keys(context).length ? context : undefined,
                });

                console.log("[ChatInput] Task created, response:", response);
                console.info("[DIAG-1] submitTask response", {
                    workflowId: response.workflow_id,
                    runId: response.run_id ?? null,
                    sessionId: response.session_id ?? null,
                });

                setQuery("");

                onTaskCreated(response.workflow_id, query.trim(), response.session_id, undefined, response.run_id);
            }
        } catch (err) {
            setError(err instanceof Error ? err.message : t("chat.submitFailed"));
        } finally {
            setIsSubmitting(false);
        }
    };

    const isInputDisabled = disabled;

    const handleKeyDown = (e: React.KeyboardEvent) => {
        const nativeEvent = e.nativeEvent as { isComposing?: boolean; keyCode?: number } | undefined;
        const isComposing =
            (e as unknown as { isComposing?: boolean }).isComposing ||
            isComposingRef.current ||
            nativeEvent?.isComposing ||
            nativeEvent?.keyCode === 229;

        // When using IME (Chinese, Japanese, etc.), do not send on Enter while composing/choosing characters
        if (isComposing) {
            return;
        }

        if (e.key === "Enter") {
            const target = e.currentTarget as HTMLElement | null;
            const isTextarea = target instanceof HTMLTextAreaElement;

            // For textarea, keep Shift+Enter as newline
            if (e.shiftKey && isTextarea) {
                return;
            }

            // For plain Enter (and Enter in single-line input), prevent default form submit
            e.preventDefault();

            if (!e.shiftKey) {
                handleSubmit(e);
            }
        }
    };

    const handleCompositionStart = () => {
        isComposingRef.current = true;
    };

    const handleCompositionEnd = () => {
        isComposingRef.current = false;
    };

    const handleFilesChange = (files: UploadedFile[]) => {
        setUploadedFiles(files);
    };

    const clearFiles = () => {
        fileUploadRef.current?.clearFiles();
        setUploadedFiles([]);
        setIsFilePanelOpen(false);
    };

    const findAnkiPayload = (value: unknown): Record<string, unknown> | null => {
        if (!value) return null;
        if (typeof value === "string") {
            try {
                return findAnkiPayload(JSON.parse(value));
            } catch {
                return null;
            }
        }
        if (Array.isArray(value)) {
            for (const item of value) {
                const found = findAnkiPayload(item);
                if (found) return found;
            }
            return null;
        }
        if (typeof value === "object") {
            const obj = value as Record<string, unknown>;
            if (obj.anki_payload && typeof obj.anki_payload === "object") {
                return obj.anki_payload as Record<string, unknown>;
            }
            for (const candidate of Object.values(obj)) {
                const found = findAnkiPayload(candidate);
                if (found) return found;
            }
        }
        return null;
    };

    const handleSaveCurrentTaskAsTemplate = async () => {
        if (!currentWorkflowId) return;
        setIsSavingFromTask(true);
        setError(null);
        try {
            const task = await getTask(currentWorkflowId);
            const ankiPayload = findAnkiPayload(task);
            if (!ankiPayload) {
                throw new Error("未找到可保存模板的输出，请先完成一次模板生成。");
            }
            const noteType = (ankiPayload.note_type || {}) as Record<string, unknown>;
            const templates = Array.isArray(noteType.templates)
                ? (noteType.templates as Array<Record<string, unknown>>)
                : [];
            const firstTemplate = templates[0] || {};
            const templateInfo = (ankiPayload.template || {}) as Record<string, unknown>;

            const sourceTemplateId = String(templateInfo.template_id || selectedTemplateId || "template");
            const generatedId = `${sourceTemplateId}-saved-${Date.now()}`;
            const generatedName = `Saved ${sourceTemplateId} ${new Date().toISOString().slice(0, 10)}`;

            await importCardTemplate({
                schema_version: "kctpl/v1",
                exported_at: new Date().toISOString(),
                template: {
                    template_id: generatedId,
                    name: generatedName,
                    description: "Saved from card template agent",
                    metadata: {
                        source_task_id: currentWorkflowId,
                        source_template_id: sourceTemplateId,
                    },
                },
                version: {
                    template_id: generatedId,
                    version: 1,
                    front_html: String(firstTemplate.qfmt || ""),
                    back_html: String(firstTemplate.afmt || ""),
                    css: String(noteType.css || ""),
                    mapping_spec: {
                        fields: noteType.fields || [],
                        render_target: ankiPayload.render_target || "anki",
                    },
                    is_published: true,
                },
            });
        } catch (err) {
            setError(err instanceof Error ? err.message : "保存模板失败");
        } finally {
            setIsSavingFromTask(false);
        }
    };

    const handleTemplateSelect = async (template: CardTemplate) => {
        setSelectedTemplateId(template.template_id);
        setSelectedTemplateVersion(template.latest_version);
        commands.setTemplatePreflight(sessionId ?? null, { ...DEFAULT_TEMPLATE_PREFLIGHT });
        setError(null);
        setIsSavingTemplatePref(true);
        try {
            await setUserTemplatePreference({
                default_template_id: template.template_id,
                default_template_version: template.latest_version,
            });
            await runTemplatePreflight(template.template_id, template.latest_version);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Template precheck failed.");
        } finally {
            setIsSavingTemplatePref(false);
        }
    };

    const AgentPopover = () => {
        if (!onSelectedAgentChange) return null;
        const agentLabel = selectedAgent === "card_template"
            ? t("chat.agentDeepResearch")
            : t("chat.agentEveryday");
        return (
            <Popover>
                <PopoverTrigger asChild>
                    <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 gap-1 text-xs"
                        aria-label={t("chat.agentLabel")}
                    >
                        {selectedAgent === "card_template" ? (
                            <LayoutTemplate className="h-4 w-4 text-violet-500" />
                        ) : (
                            <Sparkles className="h-4 w-4 text-amber-500" />
                        )}
                        <span className="max-w-[88px] truncate">{agentLabel}</span>
                        <ChevronDown className="h-3 w-3 text-muted-foreground" />
                    </Button>
                </PopoverTrigger>
                <PopoverContent align="end" className="w-56 p-2">
                    <div className="space-y-2">
                        <div className="text-xs text-muted-foreground">{t("chat.agentLabel")}</div>
                        <div className="grid gap-1">
                            <Button
                                type="button"
                                variant={selectedAgent === "normal" ? "secondary" : "ghost"}
                                size="sm"
                                className="justify-start gap-2"
                                onClick={() => onSelectedAgentChange("normal")}
                            >
                                <Sparkles className="h-4 w-4 text-amber-500" />
                                {t("chat.agentEveryday")}
                            </Button>
                            <Button
                                type="button"
                                variant={selectedAgent === "card_template" ? "secondary" : "ghost"}
                                size="sm"
                                className="justify-start gap-2"
                                onClick={() => onSelectedAgentChange("card_template")}
                            >
                                <LayoutTemplate className="h-4 w-4 text-violet-500" />
                                {t("chat.agentDeepResearch")}
                            </Button>
                        </div>
                        {selectedAgent === "card_template" && (
                            <div className="text-xs text-muted-foreground">{t("chat.templateBuilderMode")}</div>
                        )}
                    </div>
                </PopoverContent>
            </Popover>
        );
    };

    const TemplatePopover = () => {
        const selectedTemplate = templates.find((item) => item.template_id === selectedTemplateId);
        const templateLabel = selectedTemplate?.name || selectedTemplateId || t("chat.templateUnselected");

        return (
            <Popover>
                <PopoverTrigger asChild>
                    <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 gap-1 text-xs"
                        aria-label={t("chat.templateLabel")}
                    >
                        <LayoutTemplate className="h-4 w-4 text-sky-600" />
                        <span className="max-w-[98px] truncate">{templateLabel}</span>
                        <ChevronDown className="h-3 w-3 text-muted-foreground" />
                    </Button>
                </PopoverTrigger>
                <PopoverContent align="end" className="w-64 p-2">
                    <div className="space-y-2">
                        <div className="text-xs text-muted-foreground">{t("chat.templateLabel")}</div>
                        {isTemplatesLoading ? (
                            <div className="text-xs text-muted-foreground px-2 py-1">{t("chat.templateLoading")}</div>
                        ) : templates.length === 0 ? (
                            <div className="text-xs text-muted-foreground px-2 py-1">{t("chat.templateFallback")}</div>
                        ) : (
                            <div className="grid gap-1">
                                {templates.map((template) => (
                                    <Button
                                        key={template.template_id}
                                        type="button"
                                        variant={selectedTemplateId === template.template_id ? "secondary" : "ghost"}
                                        size="sm"
                                        className="justify-start"
                                        onClick={() => { void handleTemplateSelect(template); }}
                                    >
                                        <span className="truncate">{template.name}</span>
                                    </Button>
                                ))}
                            </div>
                        )}
                        {isSavingTemplatePref && (
                            <div className="text-[11px] text-muted-foreground px-2 py-1">{t("chat.templateSaving")}</div>
                        )}
                    </div>
                </PopoverContent>
            </Popover>
        );
    };

    // Centered variant for empty sessions - modern ChatGPT-style layout
    if (variant === "centered") {
        return (
            <div className="flex flex-col items-center justify-center h-full p-8" data-kc-chat-input-root="true" ref={chatInputRootRef}>
                <div className="w-full max-w-2xl space-y-6">
                    <div className="text-center space-y-2">
                        <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-primary/10 mb-4">
                            <Sparkles className="w-6 h-6 text-primary" />
                        </div>
                        <h2 className="text-2xl font-semibold tracking-tight">{t("chat.centeredTitle")}</h2>
                        <p className="text-muted-foreground">
                            {t("chat.centeredSubtitle")}
                        </p>
                    </div>

                    <div
                        className="space-y-4"
                        onSubmitCapture={(event) => {
                            event.preventDefault();
                            event.stopPropagation();
                        }}
                    >

                        <div className="relative">
                            <div className="absolute left-2 bottom-2 flex items-center gap-1 z-10">
                                {enableFileUpload && (
                                    <div ref={filePanelRef} className="relative">
                                            <Button
                                                type="button"
                                                variant={isFilePanelOpen ? "secondary" : "ghost"}
                                                size="icon"
                                                className="h-8 w-8 relative"
                                                onClick={() => setIsFilePanelOpen((prev) => !prev)}
                                                aria-label={t("common.attachFiles")}
                                            >
                                                <Paperclip className="h-4 w-4" />
                                                {uploadedFiles.length > 0 && (
                                                    <span className="absolute -top-1 -right-1 h-4 min-w-[16px] rounded-full bg-primary text-[9px] text-primary-foreground flex items-center justify-center px-1">
                                                        {uploadedFiles.length}
                                                    </span>
                                                )}
                                            </Button>
                                        <div
                                            className={cn(
                                                "absolute left-0 bottom-10 z-50 w-[min(92vw,420px)] rounded-md border bg-popover p-3 text-popover-foreground shadow-md",
                                                !isFilePanelOpen && "hidden"
                                            )}
                                        >
                                            <div className="flex items-center justify-between mb-2">
                                                <h3 className="text-sm font-medium">{t("chat.attachFilesTitle")}</h3>
                                                <Button
                                                    type="button"
                                                    variant="ghost"
                                                    size="sm"
                                                    onClick={clearFiles}
                                                    className="h-7"
                                                >
                                                    {t("common.clear")}
                                                </Button>
                                            </div>
                                            <FileUpload
                                                ref={fileUploadRef}
                                                sessionId={sessionId}
                                                onFilesChange={handleFilesChange}
                                                config={{
                                                    maxFiles,
                                                    maxFileSize,
                                                }}
                                                disabled={disabled || isSubmitting}
                                                maxHeight="220px"
                                                showManualUploadButton={false}
                                            />
                                        </div>
                                    </div>
                                )}
                                {TemplatePopover()}
                                {AgentPopover()}
                                {selectedAgent === "card_template" && currentWorkflowId && (
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        size="sm"
                                        className="h-7 px-2 gap-1 text-xs"
                                        onClick={() => { void handleSaveCurrentTaskAsTemplate(); }}
                                        disabled={isSavingFromTask}
                                    >
                                        {isSavingFromTask ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                                        Save
                                    </Button>
                                )}
                            </div>
                            <Textarea
                                placeholder={t("chat.placeholder")}
                                value={query}
                                onChange={(e) => setQuery(e.target.value)}
                                disabled={isInputDisabled || isSubmitting}
                                autoFocus={allowAutoFocus}
                                rows={4}
                                onCompositionStart={handleCompositionStart}
                                onCompositionEnd={handleCompositionEnd}
                                onKeyDown={handleKeyDown}
                                className="pr-16 pb-12 min-h-[120px] text-base"
                                aria-label={t("chat.placeholder")}
                                name="chat-input"
                                autoComplete="off"
                            />
                            {isTaskRunning ? (
                                <div className="absolute right-3 bottom-3 flex gap-1.5">
                                    {shouldShowResume && (
                                        <Button
                                            type="button"
                                            size="icon"
                                            variant="outline"
                                            onClick={onResume}
                                            disabled={!canControlTask || isResumeLoading || isCancelling}
                                            title={t("chat.resumeWorkflow")}
                                            aria-label={t("chat.resumeWorkflow")}
                                        >
                                            {isResumeLoading ? (
                                                <Loader2 className="h-4 w-4 animate-spin" />
                                            ) : (
                                                <Play className="h-4 w-4" />
                                            )}
                                        </Button>
                                    )}
                                    {shouldShowPause && (
                                        <Button
                                            type="button"
                                            size="icon"
                                            variant="outline"
                                            onClick={onPause}
                                            disabled={!canControlTask || isPauseLoading || isCancelling}
                                            title={t("chat.pauseAtCheckpoint")}
                                            aria-label={t("chat.pauseAtCheckpoint")}
                                        >
                                            {isPauseLoading ? (
                                                <Loader2 className="h-4 w-4 animate-spin" />
                                            ) : (
                                                <Pause className="h-4 w-4" />
                                            )}
                                        </Button>
                                    )}
                                    {shouldShowCancel && (
                                        <Button
                                            type="button"
                                            size="icon"
                                            variant="destructive"
                                            onClick={onCancel}
                                            disabled={!canControlTask || isCancelling || isResumeLoading}
                                            title={t("chat.stop")}
                                            aria-label={t("chat.stop")}
                                        >
                                            {isCancelling ? (
                                                <Loader2 className="h-4 w-4 animate-spin" />
                                            ) : (
                                                <Square className="h-4 w-4" />
                                            )}
                                        </Button>
                                    )}
                                </div>
                            ) : (
                                <Button
                                    type="button"
                                    size="icon"
                                    disabled={!query.trim() || isInputDisabled || isSubmitting || (selectedAgent === "normal" && !selectedTemplateId)}
                                    className="absolute right-3 bottom-3"
                                    aria-label={t("common.confirm")}
                                    onClick={() => { void handleSubmit(); }}
                                >
                                    {isSubmitting ? (
                                        <Loader2 className="h-4 w-4 animate-spin" />
                                    ) : (
                                        <Send className="h-4 w-4" />
                                    )}
                                </Button>
                            )}
                        </div>

                        {error && (
                            <p className="text-sm text-red-500 text-center">{error}</p>
                        )}
                    </div>

                    <div className="flex flex-wrap items-center justify-center gap-2 text-xs text-muted-foreground">
                        <span>{t("chat.tryLabel")}</span>
                        <button
                            type="button"
                            onClick={() => setQuery(t("chat.suggest1"))}
                            className="px-2 py-1 rounded-md bg-muted hover:bg-muted/80 transition-colors"
                        >
                            {t("chat.suggest1")}
                        </button>
                        <button
                            type="button"
                            onClick={() => setQuery(t("chat.suggest2"))}
                            className="px-2 py-1 rounded-md bg-muted hover:bg-muted/80 transition-colors"
                        >
                            {t("chat.suggest2")}
                        </button>
                        <button
                            type="button"
                            onClick={() => setQuery(t("chat.suggest3"))}
                            className="px-2 py-1 rounded-md bg-muted hover:bg-muted/80 transition-colors"
                        >
                            {t("chat.suggest3")}
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    // Default compact variant for follow-up messages
    return (
        <div
            className="space-y-2"
            data-kc-chat-input-root="true"
            ref={chatInputRootRef}
            onSubmitCapture={(event) => {
                event.preventDefault();
                event.stopPropagation();
            }}
        >
            <div className="flex gap-2 items-end">
                <div className="relative flex-1">
                    <div className="absolute left-2 bottom-2 flex items-center gap-1 z-10">
                        {enableFileUpload && (
                            <div ref={filePanelRef} className="relative">
                                    <Button
                                        type="button"
                                        variant={isFilePanelOpen ? "secondary" : "ghost"}
                                        size="icon"
                                        className="h-7 w-7 relative"
                                        onClick={() => setIsFilePanelOpen((prev) => !prev)}
                                        aria-label={t("common.attachFiles")}
                                    >
                                        <Paperclip className="h-4 w-4" />
                                        {uploadedFiles.length > 0 && (
                                            <span className="absolute -top-1 -right-1 h-4 min-w-[16px] rounded-full bg-primary text-[9px] text-primary-foreground flex items-center justify-center px-1">
                                                {uploadedFiles.length}
                                            </span>
                                        )}
                                    </Button>
                                <div
                                    className={cn(
                                        "absolute left-0 bottom-9 z-50 w-[min(92vw,400px)] rounded-md border bg-popover p-3 text-popover-foreground shadow-md",
                                        !isFilePanelOpen && "hidden"
                                    )}
                                >
                                    <div className="flex items-center justify-between mb-2">
                                        <h3 className="text-sm font-medium">{t("chat.attachFilesTitle")}</h3>
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            size="sm"
                                            onClick={clearFiles}
                                            className="h-6 text-xs"
                                        >
                                            {t("common.clear")}
                                        </Button>
                                    </div>
                                    <FileUpload
                                        ref={fileUploadRef}
                                        sessionId={sessionId}
                                        onFilesChange={handleFilesChange}
                                        config={{
                                            maxFiles,
                                            maxFileSize,
                                        }}
                                        disabled={disabled || isSubmitting}
                                        maxHeight="200px"
                                        className="text-sm"
                                        showManualUploadButton={false}
                                    />
                                </div>
                            </div>
                        )}
                        {TemplatePopover()}
                        {AgentPopover()}
                        {selectedAgent === "card_template" && currentWorkflowId && (
                            <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="h-7 px-2 gap-1 text-xs"
                                onClick={() => { void handleSaveCurrentTaskAsTemplate(); }}
                                disabled={isSavingFromTask}
                            >
                                {isSavingFromTask ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                                Save
                            </Button>
                        )}
                    </div>
                    <Textarea
                        placeholder={isInputDisabled ? t("chat.waiting") : t("chat.placeholder")}
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        disabled={isInputDisabled || isSubmitting}
                        autoFocus={allowAutoFocus}
                        rows={2}
                        onCompositionStart={handleCompositionStart}
                        onCompositionEnd={handleCompositionEnd}
                        onKeyDown={handleKeyDown}
                        className="min-h-[56px] pr-3 pl-3 pb-10 pt-2"
                        aria-label={t("chat.placeholder")}
                        name="chat-input-compact"
                        autoComplete="off"
                    />
                </div>
                {/* Show Pause/Stop buttons when task is running, otherwise show Send button */}
                {isTaskRunning ? (
                    <div className="flex gap-1.5">
                        {shouldShowResume && (
                            <Button
                                type="button"
                                size="icon"
                                variant="outline"
                                onClick={onResume}
                                disabled={!canControlTask || isResumeLoading || isCancelling}
                                title={t("chat.resumeWorkflow")}
                                aria-label={t("chat.resumeWorkflow")}
                            >
                                {isResumeLoading ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                    <Play className="h-4 w-4" />
                                )}
                            </Button>
                        )}
                        {shouldShowPause && (
                            <Button
                                type="button"
                                size="icon"
                                variant="outline"
                                onClick={onPause}
                                disabled={!canControlTask || isPauseLoading || isCancelling}
                                title={t("chat.pauseAtCheckpoint")}
                                aria-label={t("chat.pauseAtCheckpoint")}
                            >
                                {isPauseLoading ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                    <Pause className="h-4 w-4" />
                                )}
                            </Button>
                        )}
                        {shouldShowCancel && (
                            <Button
                                type="button"
                                size="icon"
                                variant="destructive"
                                onClick={onCancel}
                                disabled={!canControlTask || isCancelling || isResumeLoading}
                                title={t("chat.stop")}
                                aria-label={t("chat.stop")}
                            >
                                {isCancelling ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                    <Square className="h-4 w-4" />
                                )}
                            </Button>
                        )}
                    </div>
                ) : (
                    <Button
                        type="button"
                        size="icon"
                        disabled={!query.trim() || isInputDisabled || isSubmitting || (selectedAgent === "normal" && !selectedTemplateId)}
                        aria-label={t("common.confirm")}
                        onClick={() => { void handleSubmit(); }}
                    >
                        {isSubmitting ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                            <Send className="h-4 w-4" />
                        )}
                    </Button>
                )}
            </div>
            {error && (
                <p className="text-xs text-red-500">{error}</p>
            )}
        </div>
    );
}
