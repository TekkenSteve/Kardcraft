"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Loader2, AlertCircle } from "lucide-react";
import {
    ory,
    type LoginFlow,
    type UpdateLoginFlowBody,
} from "@/lib/kratos/client";
import { isUiNodeInputAttributes } from "@ory/integrations/ui";
import { useSessionCommands, useSessionSelector } from "@/lib/session/system";

interface LoginDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onSuccess: () => void;
    onSwitchToRegister: () => void;
}

type HttpError = {
    message?: string;
    response?: {
        status?: number;
        data?: unknown;
    };
};

const extractHttpError = (value: unknown): HttpError | null => {
    if (!value || typeof value !== "object") return null;
    return value as HttpError;
};

const collectFlowErrors = (flowData: unknown): string[] => {
    if (!flowData || typeof flowData !== "object") return [];
    const record = flowData as { ui?: { messages?: Array<{ type?: string; text?: string }>; nodes?: Array<{ messages?: Array<{ type?: string; text?: string }> }> } };

    const errors: string[] = [];
    const formMessages = record.ui?.messages ?? [];
    formMessages.forEach((message) => {
        if (message.type === "error" && typeof message.text === "string") {
            errors.push(message.text);
        }
    });

    const nodes = record.ui?.nodes ?? [];
    nodes.forEach((node) => {
        (node.messages ?? []).forEach((message) => {
            if (message.type === "error" && typeof message.text === "string") {
                errors.push(message.text);
            }
        });
    });

    return errors;
};

export function LoginDialog({
    open,
    onOpenChange,
    onSuccess,
    onSwitchToRegister,
}: LoginDialogProps) {
    const [flow, setFlow] = useState<LoginFlow | null>(null);
    const [formData, setFormData] = useState<Record<string, string>>({});
    const [errors, setErrors] = useState<string[]>([]);
    const [submitAttempted, setSubmitAttempted] = useState(false);

    const isAuthenticating = useSessionSelector((snapshot) => snapshot.matches("authenticating"));
    const isAuthenticated = useSessionSelector((snapshot) => snapshot.matches("authenticated"));
    const lastError = useSessionSelector((snapshot) => snapshot.context.lastError);
    const lastOperation = useSessionSelector((snapshot) => snapshot.context.lastOperation);
    const { login, clearError } = useSessionCommands();

    const initFlow = useCallback(async () => {
        try {
            const { data } = await ory.createBrowserLoginFlow();
            setFlow(data);
            setErrors([]);

            const initialData: Record<string, string> = {};
            data.ui.nodes.forEach((node) => {
                if (!isUiNodeInputAttributes(node.attributes)) return;
                if (node.attributes.type === "button" || node.attributes.type === "submit") return;
                initialData[node.attributes.name] = typeof node.attributes.value === "string"
                    ? node.attributes.value
                    : "";
            });
            setFormData(initialData);
        } catch (error) {
            const message = error instanceof Error ? error.message : "Unknown error";
            setErrors([`Failed to initialize login: ${message}`]);
        }
    }, []);

    const handleClose = useCallback(() => {
        onOpenChange(false);
        clearError();
        setSubmitAttempted(false);
        setFormData({});
        setErrors([]);
        setFlow(null);
    }, [clearError, onOpenChange]);

    useEffect(() => {
        if (open && !flow) {
            const timer = window.setTimeout(() => {
                void initFlow();
            }, 0);
            return () => window.clearTimeout(timer);
        }
    }, [flow, initFlow, open]);

    useEffect(() => {
        if (!submitAttempted) return;
        if (!isAuthenticated) return;

        const timer = window.setTimeout(() => {
            onSuccess();
            handleClose();
        }, 0);
        return () => window.clearTimeout(timer);
    }, [submitAttempted, isAuthenticated, onSuccess, handleClose]);

    useEffect(() => {
        if (!submitAttempted) return;
        if (lastOperation !== "login") return;
        if (!lastError) return;

        const httpError = extractHttpError(lastError);
        if (httpError?.response?.status === 400) {
            const flowData = httpError.response.data;
            if (flowData && typeof flowData === "object") {
                const timer = window.setTimeout(() => {
                    setFlow(flowData as LoginFlow);
                    setErrors(collectFlowErrors(flowData));
                }, 0);
                return () => window.clearTimeout(timer);
            }
        }

        const timer = window.setTimeout(() => {
            setErrors([httpError?.message || "Login failed. Please try again."]);
        }, 0);
        return () => window.clearTimeout(timer);
    }, [submitAttempted, lastOperation, lastError]);

    const handleInputChange = (name: string, value: string) => {
        setFormData((prev) => ({
            ...prev,
            [name]: value,
        }));
    };

    const handleSubmit = (e: FormEvent) => {
        e.preventDefault();
        if (!flow) return;

        const submitButton = getSubmitButton();
        const submitValue = submitButton?.attributes;
        const method = submitValue && isUiNodeInputAttributes(submitValue) && typeof submitValue.value === "string"
            ? submitValue.value
            : "password";

        setSubmitAttempted(true);
        setErrors([]);
        clearError();

        login({
            flowId: flow.id,
            body: {
                ...formData,
                method,
            } as UpdateLoginFlowBody,
        });
    };

    const getInputNodes = () => {
        if (!flow) return [];
        return flow.ui.nodes.filter((node) =>
            isUiNodeInputAttributes(node.attributes) &&
            node.attributes.type !== "hidden" &&
            node.attributes.type !== "submit" &&
            node.attributes.type !== "button",
        );
    };

    const getSubmitButton = () => {
        if (!flow) return null;
        return flow.ui.nodes.find((node) =>
            isUiNodeInputAttributes(node.attributes) &&
            node.attributes.type === "submit",
        ) ?? null;
    };

    return (
        <Dialog open={open} onOpenChange={handleClose}>
            <DialogContent className="sm:max-w-[425px]">
                <DialogHeader>
                    <DialogTitle>Sign In</DialogTitle>
                    <DialogDescription>
                        Enter your credentials to access your account
                    </DialogDescription>
                </DialogHeader>

                <form onSubmit={handleSubmit} className="space-y-4">
                    {errors.length > 0 && (
                        <Alert variant="destructive">
                            <AlertCircle className="size-4" />
                            <AlertDescription>
                                {errors.map((error) => (
                                    <div key={error}>{error}</div>
                                ))}
                            </AlertDescription>
                        </Alert>
                    )}

                    {getInputNodes().map((node) => {
                        if (!isUiNodeInputAttributes(node.attributes)) return null;

                        const { name, type, required, disabled } = node.attributes;
                        const value = formData[name] || "";
                        const hasError = node.messages.some((message) => message.type === "error");
                        const label = node.meta.label?.text || name;

                        return (
                            <div key={name} className="space-y-2">
                                <Label htmlFor={name}>
                                    {label}
                                    {required && <span className="text-red-500 ml-1">*</span>}
                                </Label>
                                <Input
                                    id={name}
                                    name={name}
                                    type={type}
                                    value={value}
                                    onChange={(event) => handleInputChange(name, event.target.value)}
                                    placeholder={(node.attributes as { placeholder?: string }).placeholder || ""}
                                    required={required}
                                    disabled={disabled || isAuthenticating}
                                    className={hasError ? "border-red-500" : ""}
                                />
                                {node.messages.map((message) => (
                                    <p key={message.text} className={`text-sm ${message.type === "error" ? "text-red-500" : "text-gray-600"}`}>
                                        {message.text}
                                    </p>
                                ))}
                            </div>
                        );
                    })}

                    <div className="flex flex-col gap-2">
                        <Button type="submit" disabled={isAuthenticating || !flow} className="w-full">
                            {isAuthenticating && <Loader2 className="mr-2 size-4 animate-spin" />}
                            {getSubmitButton()?.meta.label?.text || "Sign In"}
                        </Button>

                        <Button
                            type="button"
                            variant="ghost"
                            onClick={onSwitchToRegister}
                            disabled={isAuthenticating}
                            className="w-full"
                        >
                            Don&apos;t have an account? Sign up
                        </Button>
                    </div>
                </form>
            </DialogContent>
        </Dialog>
    );
}
