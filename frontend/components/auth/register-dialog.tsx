"use client";

import { useCallback, useEffect, useState } from "react";
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
  type RegistrationFlow,
  type UpdateRegistrationFlowBody,
} from "@/lib/kratos/client";
import { emitAuthStateChanged } from "@/lib/session/auth-events";
import { isUiNodeInputAttributes } from "@ory/integrations/ui";

interface RegisterDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  onSwitchToLogin: () => void;
}

type UiMessageLike = { type?: string; text?: string };
type UiNodeLike = { messages?: UiMessageLike[] };
type UiPayloadLike = { ui?: { messages?: UiMessageLike[]; nodes?: UiNodeLike[] } };
type HttpErrorLike = {
  message?: string;
  response?: {
    status?: number;
    data?: unknown;
  };
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

const asHttpError = (value: unknown): HttpErrorLike | null => {
  if (!isRecord(value)) return null;
  return value as HttpErrorLike;
};

const collectUiErrors = (value: unknown): string[] => {
  if (!isRecord(value)) return [];
  const payload = value as UiPayloadLike;
  const result: string[] = [];
  (payload.ui?.messages || []).forEach((msg) => {
    if (msg.type === "error" && typeof msg.text === "string") result.push(msg.text);
  });
  (payload.ui?.nodes || []).forEach((node) => {
    (node.messages || []).forEach((msg) => {
      if (msg.type === "error" && typeof msg.text === "string") result.push(msg.text);
    });
  });
  return result;
};

export function RegisterDialog({
  open,
  onOpenChange,
  onSuccess,
  onSwitchToLogin,
}: RegisterDialogProps) {
  const [flow, setFlow] = useState<RegistrationFlow | null>(null);
  const [formData, setFormData] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  const buildInitialData = useCallback((nextFlow: RegistrationFlow): Record<string, string> => {
    const initialData: Record<string, string> = {};
    nextFlow.ui.nodes.forEach((node) => {
      if (!isUiNodeInputAttributes(node.attributes)) return;
      if (node.attributes.type === "button" || node.attributes.type === "submit") return;
      initialData[node.attributes.name] = typeof node.attributes.value === "string"
        ? node.attributes.value
        : "";
    });
    return initialData;
  }, []);

  const initFlow = useCallback(async () => {
    try {
      const { data } = await ory.createBrowserRegistrationFlow();
      setFlow(data);
      setErrors([]);
      setFormData(buildInitialData(data));
    } catch (error) {
      console.error("Failed to create registration flow:", error);
      const errorMessage = error instanceof Error ? error.message : "Unknown error";
      setErrors([`Failed to initialize registration: ${errorMessage}`]);
    }
  }, [buildInitialData]);

  useEffect(() => {
    if (open && !flow) {
      void initFlow();
    }
  }, [open, flow, initFlow]);

  const handleInputChange = (name: string, value: string) => {
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!flow) return;

    setLoading(true);
    setErrors([]);

    try {
      // Get the method value from the submit button
      const submitButton = getSubmitButton();
      const methodAttributes = submitButton?.attributes;
      const method =
        methodAttributes && isUiNodeInputAttributes(methodAttributes) && typeof methodAttributes.value === "string"
          ? methodAttributes.value
          : "profile";
      
      // Add method field to form data
      const submitData = {
        ...formData,
        method: method
      };

      console.log("Submitting registration data:", submitData);

      const { data } = await ory.updateRegistrationFlow({
        flow: flow.id,
        updateRegistrationFlowBody: submitData as UpdateRegistrationFlowBody,
      });

      console.log("Registration successful:", data);
      
      // Handle continue_with actions
      if (data.continue_with) {
        for (const item of data.continue_with) {
          switch (item.action) {
            case "show_verification_ui":
              // For now, just show success - in a real app you'd redirect to verification
              console.log("Verification required:", item.flow?.id);
              break;
          }
        }
      }
      
      // Check if this was a successful registration (has session)
      if (data.session) {
        onSuccess();
        onOpenChange(false);
        setFormData({});
        setFlow(null);
        
        emitAuthStateChanged();
      } else {
        // This might be a multi-step flow, refresh the flow to get next step
        const { data: newFlow } = await ory.getRegistrationFlow({ id: flow.id });
        setFlow(newFlow);
        setFormData(buildInitialData(newFlow));
      }
    } catch (error: unknown) {
      console.error("Registration error:", error);

      const httpError = asHttpError(error);
      if (httpError?.response?.status === 400 && httpError.response.data) {
        // Form validation error - update flow with new data
        if (isRecord(httpError.response.data)) {
          setFlow(httpError.response.data as unknown as RegistrationFlow);
        }
        const flowErrors = collectUiErrors(httpError.response.data);
        setErrors(flowErrors);
      } else {
        setErrors([httpError?.message || "Registration failed. Please try again."]);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    onOpenChange(false);
    setFormData({});
    setErrors([]);
    setFlow(null);
  };

  // Helper function to get input nodes
  const getInputNodes = () => {
    if (!flow) return [];
    return flow.ui.nodes.filter(node => 
      isUiNodeInputAttributes(node.attributes) && 
      node.attributes.type !== "hidden" &&
      node.attributes.type !== "submit" &&
      node.attributes.type !== "button"
    );
  };

  // Helper function to get submit button
  const getSubmitButton = () => {
    if (!flow) return null;
    return flow.ui.nodes.find(node => 
      isUiNodeInputAttributes(node.attributes) && 
      node.attributes.type === "submit"
    );
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>Create Account</DialogTitle>
          <DialogDescription>
            Sign up to get started with Kardcraft
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

          {/* Render input fields dynamically based on flow */}
          {getInputNodes().map((node) => {
            if (!isUiNodeInputAttributes(node.attributes)) return null;
            
            const { name, type, required, disabled } = node.attributes;
            const value = formData[name] || "";
            const hasError = node.messages.some(m => m.type === "error");
            const label = node.meta.label?.text || name;
            const attributesRecord = node.attributes as unknown as Record<string, unknown>;
            const placeholder =
              typeof attributesRecord.placeholder === "string"
                ? attributesRecord.placeholder
                : "";

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
                  onChange={(e) => handleInputChange(name, e.target.value)}
                  placeholder={placeholder}
                  required={required}
                  disabled={disabled || loading}
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
            <Button type="submit" disabled={loading || !flow} className="w-full">
              {loading && <Loader2 className="mr-2 size-4 animate-spin" />}
              {getSubmitButton()?.meta.label?.text || "Create Account"}
            </Button>

            <Button
              type="button"
              variant="ghost"
              onClick={onSwitchToLogin}
              disabled={loading}
              className="w-full"
            >
              Already have an account? Sign in
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
