"use client";

import { useState, useEffect } from "react";
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

interface LoginDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  onSwitchToRegister: () => void;
}

export function LoginDialog({
  open,
  onOpenChange,
  onSuccess,
  onSwitchToRegister,
}: LoginDialogProps) {
  const [flow, setFlow] = useState<LoginFlow | null>(null);
  const [formData, setFormData] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  useEffect(() => {
    if (open && !flow) {
      initFlow();
    }
  }, [open]);

  const initFlow = async () => {
    try {
      const { data } = await ory.createBrowserLoginFlow();
      setFlow(data);
      setErrors([]);

      // Initialize form data with default values from the flow
      const initialData: Record<string, any> = {};
      data.ui.nodes.forEach((node) => {
        if (isUiNodeInputAttributes(node.attributes)) {
          if (node.attributes.type !== "button" && node.attributes.type !== "submit") {
            initialData[node.attributes.name] = node.attributes.value || "";
          }
        }
      });
      setFormData(initialData);
    } catch (error) {
      console.error("Failed to create login flow:", error);
      const errorMessage = error instanceof Error ? error.message : "Unknown error";
      setErrors([`Failed to initialize login: ${errorMessage}`]);
    }
  };

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
      const method = (submitButton?.attributes as any)?.value || "password";

      // Add method field to form data
      const submitData = {
        ...formData,
        method: method
      };

      console.log("Submitting login data:", submitData);

      const { data } = await ory.updateLoginFlow({
        flow: flow.id,
        updateLoginFlowBody: submitData as UpdateLoginFlowBody,
      });

      console.log("Login successful:", data);
      
      // Debug: Check if cookies were set
      setTimeout(() => {
        console.log("Cookies after login:", document.cookie);
        const kratosSession = document.cookie.split(';').find(c => c.trim().startsWith('ory_kratos_session='));
        console.log("Kratos session cookie:", kratosSession);
      }, 100);
      
      onSuccess();
      onOpenChange(false);
      setFormData({});
      setFlow(null);
      
      // Trigger a custom event to notify other components
      window.dispatchEvent(new CustomEvent('auth-state-changed'));
    } catch (error: any) {
      console.error("Login error:", error);

      if (error.response?.status === 400) {
        // Form validation error - update flow with new data
        setFlow(error.response.data);
        const flowErrors: string[] = [];

        if (error.response.data.ui?.messages) {
          flowErrors.push(...error.response.data.ui.messages.filter((m: any) => m.type === "error").map((m: any) => m.text));
        }

        error.response.data.ui?.nodes?.forEach((node: any) => {
          if (node.messages) {
            flowErrors.push(...node.messages.filter((m: any) => m.type === "error").map((m: any) => m.text));
          }
        });

        setErrors(flowErrors);
      } else {
        setErrors([error.message || "Login failed. Please try again."]);
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
          <DialogTitle>Sign In</DialogTitle>
          <DialogDescription>
            Enter your credentials to access your account
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {errors.length > 0 && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                {errors.map((error, i) => (
                  <div key={i}>{error}</div>
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
                  placeholder={(node.attributes as any).placeholder || ""}
                  required={required}
                  disabled={disabled || loading}
                  className={hasError ? "border-red-500" : ""}
                />
                {node.messages.map((message, i) => (
                  <p key={i} className={`text-sm ${message.type === "error" ? "text-red-500" : "text-gray-600"}`}>
                    {message.text}
                  </p>
                ))}
              </div>
            );
          })}

          <div className="flex flex-col gap-2">
            <Button type="submit" disabled={loading || !flow} className="w-full">
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {getSubmitButton()?.meta.label?.text || "Sign In"}
            </Button>

            <Button
              type="button"
              variant="ghost"
              onClick={onSwitchToRegister}
              disabled={loading}
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
