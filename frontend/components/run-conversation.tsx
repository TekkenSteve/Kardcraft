"use client";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { RunMessage } from "@/lib/run/types";
import type { ProcessProgress } from "@/lib/run/process-progress";
import { getSessionDisplayName } from "@/lib/session/profile";
import { useSessionSelector } from "@/lib/session/system";
import { cn, openExternalUrl } from "@/lib/utils";
import "highlight.js/styles/github-dark.css";
import { AlertCircle, Check, CheckCircle, Copy, ExternalLink, File, FileAudio, FileText, FileVideo, Image as ImageIcon, Loader2, Microscope, Paperclip, Sparkles, XCircle } from "lucide-react";
import React, { useMemo, useState, type ComponentPropsWithoutRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

export interface Citation {
    url: string;
    title?: string;
    source?: string;
    source_type?: string;
    retrieved_at?: string;
    published_date?: string;
    credibility_score?: number;
}

const coerceContentToString = (value: unknown): string => {
    if (typeof value === "string") return value;
    if (value === null || value === undefined) return "";
    if (typeof value !== "object") return String(value);
    const record = value as Record<string, unknown>;
    const fallback = record.text ?? record.message ?? record.response ?? record.content;
    if (typeof fallback === "string") return fallback;
    return JSON.stringify(value, null, 2);
};

const extractDisplayMessageFromEnvelope = (raw: string): string | null => {
    const trimmed = raw.trim();
    if (!(trimmed.startsWith("{") && trimmed.endsWith("}"))) return null;
    try {
        const parsed = JSON.parse(trimmed) as unknown;
        const queue: unknown[] = [parsed];
        const visited = new Set<unknown>();
        while (queue.length > 0) {
            const current = queue.shift();
            if (!current || typeof current !== "object" || visited.has(current)) continue;
            visited.add(current);
            const record = current as Record<string, unknown>;

            const message = record.message;
            if (typeof message === "string" && message.trim().length > 0 && message.trim().length < 400) {
                return message.trim();
            }

            if ("result" in record) queue.push(record.result);
            if ("data" in record) queue.push(record.data);
            for (const value of Object.values(record)) {
                if (value && typeof value === "object") queue.push(value);
            }
        }
    } catch {
        return null;
    }
    return null;
};

type MarkdownComponentProps<Tag extends keyof React.JSX.IntrinsicElements> = ComponentPropsWithoutRef<Tag>;
type MarkdownCodeProps = MarkdownComponentProps<"code"> & { inline?: boolean };
const getInitials = (value: string): string => {
    const trimmed = value.trim();
    if (!trimmed) return "?";
    return trimmed
        .split(" ")
        .filter(Boolean)
        .map((part) => part[0])
        .join("")
        .toUpperCase()
        .slice(0, 2);
};

type Message = RunMessage & {
    sender?: string;
    metadata?: RunMessage["metadata"] & {
        usage?: {
            total_tokens: number;
            input_tokens: number;
            output_tokens: number;
        };
        model?: string;
        provider?: string;
        citations?: Citation[];
    };
    toolData?: unknown;
};

type MessageAttachment = {
    fileId: string;
    filename: string;
    size: number;
    mimeType: string;
};

const normalizeAttachment = (value: unknown): MessageAttachment | null => {
    if (!value || typeof value !== "object") return null;
    const raw = value as Record<string, unknown>;
    const fileId = String(raw.fileId ?? "").trim();
    const filename = String(raw.filename ?? "").trim();
    if (!fileId || !filename) return null;

    const sizeRaw = raw.size;
    const size = typeof sizeRaw === "number" && Number.isFinite(sizeRaw) ? sizeRaw : 0;
    const mimeTypeRaw = raw.mimeType;
    const mimeType = typeof mimeTypeRaw === "string" ? mimeTypeRaw : "application/octet-stream";

    return {
        fileId,
        filename,
        size,
        mimeType,
    };
};

const extractMessageAttachments = (message: Message): MessageAttachment[] => {
    const candidates: unknown[] = [];
    if (Array.isArray(message.attachments)) {
        candidates.push(...message.attachments);
    }

    const metadata = message.metadata as Record<string, unknown> | undefined;
    if (metadata) {
        if (Array.isArray(metadata.attachments)) candidates.push(...metadata.attachments);
        if (Array.isArray(metadata.files)) candidates.push(...metadata.files);
    }

    const normalized = candidates
        .map((item) => normalizeAttachment(item))
        .filter((item): item is MessageAttachment => item !== null);

    const seen = new Set<string>();
    return normalized.filter((item) => {
        const key = `${item.fileId}:${item.filename}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });
};

interface RunConversationProps {
    messages: readonly Message[];
    agentType?: "normal" | "card_template";
    isWaitingForAssistant?: boolean;
    processProgress?: ProcessProgress | null;
}

// Component to render a single citation with tooltip
function CitationLink({ index, citation }: { index: number; citation: Citation }) {
    const displayTitle = citation.title || citation.source || citation.url;
    const publishedDate = citation.published_date ? new Date(citation.published_date).toLocaleDateString() : null;
    const { t } = useTranslation();

    return (
        <TooltipProvider delayDuration={200}>
            <Tooltip>
                <TooltipTrigger asChild>
                    <a
                        href={citation.url}
                        className="inline-flex items-baseline text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 font-medium no-underline hover:underline mx-0.5 cursor-pointer"
                        onClick={(e) => {
                            e.preventDefault();
                            openExternalUrl(citation.url);
                        }}
                    >
                        [{index}]
                    </a>
                </TooltipTrigger>
                <TooltipContent
                    side="top"
                    className="max-w-sm p-3 space-y-2"
                    sideOffset={5}
                >
                    <div className="space-y-1">
                        <div className="font-semibold text-sm line-clamp-2">
                            {displayTitle}
                        </div>
                        {citation.source && (
                            <div className="text-xs text-muted-foreground flex items-center gap-1">
                                <ExternalLink className="size-3" />
                                <span className="truncate">{citation.source}</span>
                            </div>
                        )}
                        {publishedDate && (
                            <div className="text-xs text-muted-foreground">
                                {t("chat.published")}: {publishedDate}
                            </div>
                        )}
                        {citation.credibility_score !== undefined && citation.credibility_score > 0 && (
                            <div className="text-xs text-muted-foreground">
                                {t("chat.credibility")}: {(citation.credibility_score * 100).toFixed(0)}%
                            </div>
                        )}
                    </div>
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
}

// Component to render file attachments
function FileAttachment({ file }: { file: { fileId: string; filename: string; size: number; mimeType: string } }) {
    const formatFileSize = (bytes: number): string => {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    };

    const getFileIcon = (mimeType: string) => {
        if (mimeType.startsWith('image/')) return <ImageIcon className="size-4" />;
        if (mimeType.startsWith('video/')) return <FileVideo className="size-4" />;
        if (mimeType.startsWith('audio/')) return <FileAudio className="size-4" />;
        if (mimeType.includes('pdf') || mimeType.includes('document')) return <FileText className="size-4" />;
        return <File className="size-4" />;
    };

    return (
        <div className="inline-flex items-center gap-2 px-2 py-1.5 rounded-md bg-muted/50 border border-border/50 text-xs">
            {getFileIcon(file.mimeType)}
            <div className="flex flex-col">
                <span className="font-medium truncate max-w-[200px]">{file.filename}</span>
                <span className="text-muted-foreground text-[10px]">{formatFileSize(file.size)}</span>
            </div>
        </div>
    );
}

// Component to render text with citation links
function TextWithCitations({ text, citations }: { text: string; citations?: Citation[] }) {
    if (!citations || citations.length === 0 || typeof text !== 'string') {
        return <>{text}</>;
    }

    console.log("[Citations] Processing text:", text.substring(0, 100), "Citations count:", citations.length);

    // Parse citations like [1], [2], etc.
    const citationRegex = /\[(\d+)\]/g;
    const parts: (string | ReactNode)[] = [];
    let lastIndex = 0;
    let match;
    let matchCount = 0;

    while ((match = citationRegex.exec(text)) !== null) {
        matchCount++;
        const fullMatch = match[0];
        const citationIndex = parseInt(match[1], 10);
        const citation = citations[citationIndex - 1]; // Citations are 1-indexed

        console.log("[Citations] Found match:", fullMatch, "Index:", citationIndex, "Has citation:", !!citation);

        // Add text before citation
        if (match.index > lastIndex) {
            parts.push(text.substring(lastIndex, match.index));
        }

        // Add citation link with tooltip
        if (citation) {
            parts.push(
                <CitationLink
                    key={`citation-${match.index}-${citationIndex}`}
                    index={citationIndex}
                    citation={citation}
                />
            );
        } else {
            // Citation not found in metadata, render as plain text
            parts.push(fullMatch);
        }

        lastIndex = match.index + fullMatch.length;
    }

    console.log("[Citations] Total matches found:", matchCount);

    // Add remaining text
    if (lastIndex < text.length) {
        parts.push(text.substring(lastIndex));
    }

    return <>{parts}</>;
}

// Component to render markdown with inline citation components
export function MarkdownWithCitations({ content, citations }: { content: string; citations?: Citation[] }) {
    const { t } = useTranslation();
    // Ensure content is a string - handle object content gracefully
    const coerced = coerceContentToString(content);
    const displayContent = extractDisplayMessageFromEnvelope(coerced) || coerced;

    const trimmed = typeof displayContent === "string" ? displayContent.trim() : "";
    const isLikelyJson = trimmed.startsWith("{") && trimmed.endsWith("}") && trimmed.length > 200;
    if (isLikelyJson) {
        return (
            <details className="group rounded-md border border-border/60 bg-muted/20">
                <summary className="cursor-pointer select-none px-2 py-1 text-xs font-medium text-foreground/70 hover:text-foreground">
                    {t("chat.rawPayload")}
                    <span className="ml-2 rounded-full border border-border/70 bg-background/70 px-2 py-0.5 text-[10px] text-muted-foreground">
                        {t("chat.clickToExpand")}
                    </span>
                </summary>
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-md bg-background/60 p-2 text-xs leading-relaxed text-foreground">
                    {displayContent}
                </pre>
            </details>
        );
    }

    if (!citations || citations.length === 0) {
        return (
            <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
                components={getMarkdownComponents()}
            >
                {displayContent}
            </ReactMarkdown>
        );
    }

    console.log("[MarkdownWithCitations] Rendering with citations:", citations.length);

    // Custom component to handle text nodes with citations
    const components = {
        ...getMarkdownComponents(),
        // Override paragraph to process citations inline
        p: ({ children, ...props }: MarkdownComponentProps<"p">) => {
            const processedChildren = React.Children.map(children, (child, index) => {
                if (typeof child === 'string') {
                    return <TextWithCitations key={index} text={child} citations={citations} />;
                }
                return child;
            });
            return <p className="leading-relaxed break-words" {...props}>{processedChildren}</p>;
        },
        // Also handle other text containers
        li: ({ children, ...props }: MarkdownComponentProps<"li">) => {
            const processedChildren = React.Children.map(children, (child, index) => {
                if (typeof child === 'string') {
                    return <TextWithCitations key={index} text={child} citations={citations} />;
                }
                return child;
            });
            return <li {...props}>{processedChildren}</li>;
        },
        td: ({ children, ...props }: MarkdownComponentProps<"td">) => {
            const processedChildren = React.Children.map(children, (child, index) => {
                if (typeof child === 'string') {
                    return <TextWithCitations key={index} text={child} citations={citations} />;
                }
                return child;
            });
            return <td {...props}>{processedChildren}</td>;
        },
    };

    return (
        <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeHighlight]}
            components={components}
        >
            {displayContent}
        </ReactMarkdown>
    );
}

// Extract markdown components for reuse
function getMarkdownComponents() {
    return {
        code: ({ inline, className, children, ...props }: MarkdownCodeProps) => {
            return inline ? (
                <code className={cn("px-1.5 py-0.5 rounded bg-muted/50 font-mono text-xs break-all", className)} {...props}>
                    {children}
                </code>
            ) : (
                <code className={cn("block p-3 rounded-lg bg-muted/50 overflow-x-auto whitespace-pre font-mono text-xs", className)} {...props}>
                    {children}
                </code>
            );
        },
        pre: ({ children, ...props }: MarkdownComponentProps<"pre">) => (
            <pre className="my-2 overflow-x-auto rounded-lg bg-black/90 dark:bg-black/50 p-0 whitespace-pre" {...props}>
                {children}
            </pre>
        ),
        p: ({ children, ...props }: MarkdownComponentProps<"p">) => (
            <p className="leading-relaxed break-words" {...props}>{children}</p>
        ),
        // Headings
        h1: ({ children, ...props }: MarkdownComponentProps<"h1">) => (
            <h1 className="mt-2 mb-1 font-semibold text-2xl" {...props}>{children}</h1>
        ),
        h2: ({ children, ...props }: MarkdownComponentProps<"h2">) => (
            <h2 className="mt-2 mb-1 font-semibold text-xl" {...props}>{children}</h2>
        ),
        h3: ({ children, ...props }: MarkdownComponentProps<"h3">) => (
            <h3 className="mt-1.5 mb-1 font-semibold text-lg" {...props}>{children}</h3>
        ),
        h4: ({ children, ...props }: MarkdownComponentProps<"h4">) => (
            <h4 className="mt-1.5 mb-0.5 font-semibold text-base" {...props}>{children}</h4>
        ),
        h5: ({ children, ...props }: MarkdownComponentProps<"h5">) => (
            <h5 className="mt-1 mb-0.5 font-semibold text-sm" {...props}>{children}</h5>
        ),
        h6: ({ children, ...props }: MarkdownComponentProps<"h6">) => (
            <h6 className="mt-1 mb-0.5 font-semibold text-xs" {...props}>{children}</h6>
        ),
        // Lists
        ul: ({ children, ...props }: MarkdownComponentProps<"ul">) => (
            <ul className="ml-4 list-outside list-disc space-y-0.5" {...props}>{children}</ul>
        ),
        ol: ({ children, ...props }: MarkdownComponentProps<"ol">) => (
            <ol className="ml-4 list-outside list-decimal space-y-0.5" {...props}>{children}</ol>
        ),
        // Blockquote
        blockquote: ({ children, ...props }: MarkdownComponentProps<"blockquote">) => (
            <blockquote className="border-l-4 pl-4 italic text-muted-foreground my-2" {...props}>{children}</blockquote>
        ),
        a: ({ children, href, ...props }: MarkdownComponentProps<"a">) => (
            <a
                className="underline hover:text-primary cursor-pointer break-all overflow-wrap-anywhere"
                href={href}
                onClick={(e) => {
                    if (href && (href.startsWith('http://') || href.startsWith('https://'))) {
                        e.preventDefault();
                        openExternalUrl(href);
                    }
                }}
                {...props}
            >
                {children}
            </a>
        ),
    };
}

export function RunConversation({ messages, agentType = "normal", isWaitingForAssistant = false, processProgress = null }: RunConversationProps) {
    const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
    const { t } = useTranslation();
    const userName = useSessionSelector((snapshot) => getSessionDisplayName(snapshot.context.session));
    const userLabel = userName || t("chat.you");
    const userInitials = getInitials(userLabel);

    // Debug: Check message rendering
    console.log('[RunConversation] rendering messages:', {
      count: messages.length,
      ids: messages.map(m => m.id),
      hasGenerating: messages.some(m => m.isGenerating),
      hasStreaming: messages.some(m => m.isStreaming),
      firstId: messages[0]?.id,
    });

    // Debug: Check if any messages have citations
    const messagesWithCitations = messages.filter(m => m.metadata?.citations && m.metadata.citations.length > 0);
    if (messagesWithCitations.length > 0) {
        console.log("[Citations] Messages with citations:", messagesWithCitations.length);
        messagesWithCitations.forEach(m => {
            console.log("[Citations] Message:", m.id, "Citations:", m.metadata?.citations?.length);
        });
    }

    // Copy message content to clipboard
    const handleCopyMessage = async (messageId: string, content: string) => {
        try {
            await navigator.clipboard.writeText(content);
            setCopiedMessageId(messageId);
            // Reset the copied state after 2 seconds
            setTimeout(() => {
                setCopiedMessageId(null);
            }, 2000);
        } catch (err) {
            console.error(t("chat.failedToCopy"), err);
        }
    };

    const displayedMessages = useMemo(() => messages, [messages]);

    return (
        <div className="space-y-2 p-3 sm:p-4 overflow-hidden">
            {displayedMessages.map((message) => {
                const messageLabel = message.role === "user" ? userLabel : (message.sender || message.role);
                const attachments = extractMessageAttachments(message);
                // Render user and final assistant messages normally
                return (
                    <div
                        key={message.id}
                        id={`message-${message.id}`}
                        className={cn(
                            "flex gap-2 sm:gap-3",
                            message.role === "user" ? "flex-row-reverse" : "flex-row"
                        )}
                        style={{ contentVisibility: "auto", containIntrinsicSize: "1px 180px" }}
                    >
                        <Avatar className="size-7 sm:h-8 sm:w-8 shrink-0">
                            <AvatarFallback className={cn(
                                message.role === "user" ? "bg-primary text-primary-foreground" :
                                    message.role === "system" ? (message.isError ? "bg-red-100 dark:bg-red-900/30" : message.isCancelled ? "bg-yellow-100 dark:bg-yellow-900/30" : "bg-gray-100 dark:bg-gray-900/30") :
                                        agentType === "card_template" ? "bg-violet-100 dark:bg-violet-900/30" : "bg-amber-100 dark:bg-amber-900/30"
                            )}>
                                {message.role === "user" ? userInitials :
                                    message.role === "system" ? (message.isError ? <AlertCircle className="size-4 text-red-500" /> : message.isCancelled ? <XCircle className="size-4 text-yellow-600" /> : "S") :
                                        agentType === "card_template" ? <Microscope className="size-4 text-violet-500" /> : <Sparkles className="size-4 text-amber-500" />}
                            </AvatarFallback>
                        </Avatar>
                        <div className={cn(
                            "flex max-w-[85%] sm:max-w-[80%] flex-col gap-1 min-w-0",
                            message.role === "user" ? "items-end" : "items-start"
                        )}>
                            <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-xs font-medium text-muted-foreground">
                                    {messageLabel}
                                </span>
                                <span className="text-xs text-muted-foreground">
                                    {message.timestamp}
                                </span>
                                {message.role === "user" && attachments.length > 0 && (
                                    <div className="flex items-center gap-1.5 max-w-full">
                                        {attachments.map((file) => (
                                            <span
                                                key={`meta-${file.fileId}`}
                                                className="inline-flex items-center gap-1 rounded-full border border-border/70 bg-muted/50 px-2 py-0.5 text-[11px] text-muted-foreground max-w-[180px]"
                                                title={file.filename}
                                            >
                                                <Paperclip className="size-3 shrink-0" />
                                                <span className="truncate">{file.filename}</span>
                                            </span>
                                        ))}
                                    </div>
                                )}
                            </div>
                            <div className="space-y-2 min-w-0 w-full">
                                {/* Display file attachments if present */}
                                {message.role !== "user" && attachments.length > 0 && (
                                    <div className="flex flex-wrap gap-2 mb-2">
                                        {attachments.map((file) => (
                                            <FileAttachment key={file.fileId} file={file} />
                                        ))}
                                    </div>
                                )}
                                <Card className={cn(
                                    "px-2 sm:px-3 py-1 text-sm prose prose-sm max-w-none prose-p:my-0.5 prose-p:leading-relaxed prose-ul:my-0.5 prose-ol:my-0.5 prose-li:my-0 prose-headings:mt-2 prose-headings:mb-0.5 prose-headings:leading-tight break-words overflow-wrap-anywhere overflow-hidden prose-pre:whitespace-pre-wrap prose-pre:break-all",
                                    message.role === "user" ? "bg-primary text-primary-foreground [&_a]:text-primary-foreground [&_a]:underline [&_a]:decoration-primary-foreground/50 [&_a:hover]:text-primary-foreground/80 [&_a:hover]:decoration-primary-foreground" :
                                        message.role === "system" ? (message.isError ? "bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 border-red-200 dark:border-red-800" : message.isCancelled ? "bg-yellow-50 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-300 border-yellow-200 dark:border-yellow-800" : "bg-gray-50 dark:bg-gray-900/20") :
                                            "bg-muted dark:prose-invert"
                                )}>
                                    {message.isGenerating ? (
                                        <span className="flex items-center gap-1 text-muted-foreground">
                                            <span className="inline-block w-1.5 h-1.5 bg-current rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                                            <span className="inline-block w-1.5 h-1.5 bg-current rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                                            <span className="inline-block w-1.5 h-1.5 bg-current rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                                        </span>
                                    ) : (
                                        <>
                                            <MarkdownWithCitations
                                                content={message.content}
                                                citations={message.metadata?.citations}
                                            />
                                            {message.isStreaming && (
                                                <span className="inline-block w-2 h-4 ml-1 bg-current animate-pulse" />
                                            )}
                                        </>
                                    )}
                                </Card>
                                {/* Action buttons below the card - modern design pattern */}
                                {!message.isGenerating && (
                                    <div className="flex items-center gap-1 ml-1">
                                        <TooltipProvider>
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <Button
                                                        variant="ghost"
                                                        size="sm"
                                                        className="size-5 p-0 hover:bg-muted"
                                                        onClick={() => handleCopyMessage(message.id, message.content)}
                                                    >
                                                        {copiedMessageId === message.id ? (
                                                            <Check className="size-3" />
                                                        ) : (
                                                            <Copy className="size-3" />
                                                        )}
                                                    </Button>
                                                </TooltipTrigger>
                                                <TooltipContent>
                                                    <p>{copiedMessageId === message.id ? t("chat.copied") : t("chat.copy")}</p>
                                                </TooltipContent>
                                            </Tooltip>
                                        </TooltipProvider>
                                    </div>
                                )}
                                {message.metadata?.usage && (
                                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                                        <span>{message.metadata.usage.total_tokens} {t("runDetail.tokensLabel")}</span>
                                        <span>•</span>
                                        <span>
                                            {message.metadata.model}
                                            {message.metadata.provider && ` (${message.metadata.provider})`}
                                        </span>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                );
            })}
            {(isWaitingForAssistant || processProgress) && (
                <div
                    className="flex items-center justify-center py-2 animate-in fade-in-0 slide-in-from-bottom-2 duration-300"
                >
                    <div
                        className="flex max-w-full items-center gap-2 rounded-md bg-muted/50 px-3 py-1.5 text-xs text-muted-foreground"
                        role="status"
                        aria-live="polite"
                        aria-label={t("chat.assistantWorking", "Assistant is working")}
                    >
                        {processProgress?.status === "failed" ? (
                            <AlertCircle className="size-3.5 shrink-0 text-destructive" />
                        ) : processProgress?.status === "completed" ? (
                            <CheckCircle className="size-3.5 shrink-0 text-emerald-600" />
                        ) : (
                            <Loader2 className="size-3.5 shrink-0 animate-spin" />
                        )}
                        <span className="truncate">
                            {processProgress
                                ? t(`chat.processProgress.${processProgress.status}`, {
                                    node: processProgress.label,
                                    defaultValue: `${processProgress.label} ${processProgress.status}`,
                                })
                                : t("chat.assistantWorking", "Assistant is working")}
                        </span>
                    </div>
                </div>
            )}
        </div>
    );
}
