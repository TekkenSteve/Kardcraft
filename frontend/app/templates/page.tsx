"use client";

import { useEffect, useState, type ChangeEventHandler } from "react";
import useSWR from "swr";
import { useTranslation } from "react-i18next";
import { LayoutTemplate, CheckCircle2, Loader2, Download, Upload, Eye } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
    listCardTemplates,
    setUserTemplatePreference,
    exportCardTemplate,
    importCardTemplate,
    previewCardTemplate,
    validateCardTemplate,
    getTemplateRequiredFields,
    precheckCardTemplate,
    toUiErrorMessage,
    TemplatePreviewResponse,
    TemplateValidationResponse,
    TemplateRequiredFieldsResponse,
    TemplatePrecheckResponse,
    TemplatePackageV1,
    CardTemplateListResponse,
} from "@/lib/kardcraft/api";

const templatesFetcher = async (): Promise<CardTemplateListResponse> => {
    return listCardTemplates(100, 0);
};

export default function TemplatesPage() {
    const { t } = useTranslation();
    const [savingTemplateId, setSavingTemplateId] = useState<string | null>(null);
    const [exportingTemplateId, setExportingTemplateId] = useState<string | null>(null);
    const [importing, setImporting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [previewTemplateId, setPreviewTemplateId] = useState<string | null>(null);
    const [previewTemplateVersion, setPreviewTemplateVersion] = useState<number>(1);
    const [previewingTemplateId, setPreviewingTemplateId] = useState<string | null>(null);
    const [previewData, setPreviewData] = useState<TemplatePreviewResponse | null>(null);
    const [validationData, setValidationData] = useState<TemplateValidationResponse | null>(null);
    const [requiredFieldsData, setRequiredFieldsData] = useState<TemplateRequiredFieldsResponse | null>(null);
    const [precheckData, setPrecheckData] = useState<TemplatePrecheckResponse | null>(null);
    const [previewTemplateProfile, setPreviewTemplateProfile] = useState<string>("");
    const [previewMode, setPreviewMode] = useState<"safe" | "high_fidelity">("high_fidelity");

    const { data, isLoading, mutate } = useSWR<CardTemplateListResponse>(
        "card-templates",
        templatesFetcher,
        {
            revalidateOnFocus: true,
            dedupingInterval: 10_000,
        }
    );

    const templates = data?.templates || [];
    const userDefaultTemplateId = data?.user_default_template_id || "";

    const handleSetDefault = async (templateId: string, version: number) => {
        setSavingTemplateId(templateId);
        setError(null);
        try {
            await setUserTemplatePreference({
                default_template_id: templateId,
                default_template_version: version,
            });
            await mutate();
        } catch (err) {
            setError(toUiErrorMessage(err, t("templates.saveFailed")));
        } finally {
            setSavingTemplateId(null);
        }
    };

    const handleExportTemplate = async (templateId: string, version: number) => {
        setExportingTemplateId(templateId);
        setError(null);
        try {
            const payload = await exportCardTemplate(templateId, version);
            const blob = new Blob([JSON.stringify(payload, null, 2)], {
                type: "application/json",
            });
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement("a");
            anchor.href = url;
            anchor.download = `${templateId}-v${version}.kctpl.json`;
            anchor.click();
            URL.revokeObjectURL(url);
        } catch (err) {
            setError(toUiErrorMessage(err, t("templates.exportFailed")));
        } finally {
            setExportingTemplateId(null);
        }
    };

    const handleImportFile: ChangeEventHandler<HTMLInputElement> = async (event) => {
        const file = event.target.files?.[0];
        if (!file) return;

        setImporting(true);
        setError(null);
        try {
            const text = await file.text();
            const parsed = JSON.parse(text) as Partial<TemplatePackageV1> & Record<string, unknown>;
            let imported: { ok: boolean; template_id: string; version: number; schema_version?: string } | null = null;
            if (parsed.schema_version === "kctpl/v1" && parsed.template && parsed.version) {
                imported = await importCardTemplate(parsed as TemplatePackageV1);
            } else {
                // Backward compatibility for legacy flat JSON files.
                const versionPayload = (parsed.version as Record<string, unknown>) || {};
                const templatePayload = (parsed.template as Record<string, unknown>) || {};
                imported = await importCardTemplate({
                    template_id: String(templatePayload.template_id || parsed.template_id || ""),
                    name: String(templatePayload.name || parsed.name || "Imported Template"),
                    description: (templatePayload.description as string) || (parsed.description as string) || undefined,
                    version: Number(versionPayload.version || parsed.version || 1),
                    front_html: String(versionPayload.front_html || parsed.front_html || ""),
                    back_html: String(versionPayload.back_html || parsed.back_html || ""),
                    css: String(versionPayload.css || parsed.css || ""),
                    js: (versionPayload.js as string) || (parsed.js as string) || undefined,
                    tags: templatePayload.tags || parsed.tags,
                    metadata: templatePayload.metadata || parsed.metadata,
                    assets_manifest: versionPayload.assets_manifest || parsed.assets_manifest,
                    mapping_spec: versionPayload.mapping_spec || parsed.mapping_spec,
                    compatibility: versionPayload.compatibility || parsed.compatibility,
                    changelog: (versionPayload.changelog as string) || (parsed.changelog as string) || undefined,
                    is_published: (versionPayload.is_published as boolean) ?? (parsed.is_published as boolean) ?? true,
                });
            }
            if (imported?.template_id) {
                try {
                    await validateCardTemplate({
                        template_id: imported.template_id,
                        version: imported.version,
                    });
                } catch (validationErr) {
                    const validationMessage = toUiErrorMessage(validationErr, t("templates.validationFailed"));
                    setError(t("templates.importedValidationFailed", { detail: validationMessage }));
                }
            }
            await mutate();
        } catch (err) {
            setError(toUiErrorMessage(err, t("templates.importFailed")));
        } finally {
            setImporting(false);
            event.target.value = "";
        }
    };

    useEffect(() => {
        if (!previewTemplateId) return;
        const templateId = previewTemplateId;
        let active = true;
        const run = async () => {
            setPreviewingTemplateId(templateId);
            setError(null);
            try {
                const data = await previewCardTemplate({
                    template_id: templateId,
                    version: previewTemplateVersion,
                    render_target: "anki",
                    template_profile: previewTemplateProfile || undefined,
                    preview_mode: previewMode,
                });

                const [validation, requiredFields] = await Promise.all([
                    validateCardTemplate({
                        template_id: templateId,
                        version: previewTemplateVersion,
                        template_profile: previewTemplateProfile || undefined,
                    }),
                    getTemplateRequiredFields({
                        template_id: templateId,
                        version: previewTemplateVersion,
                    }),
                ]);

                const sampleFields: Record<string, string> = {};
                const noteFields = validation.note_fields.length > 0 ? validation.note_fields : data.note_fields;
                for (const field of noteFields) {
                    sampleFields[field] = `${field} sample value`;
                }
                const precheck = await precheckCardTemplate({
                    template_id: templateId,
                    version: previewTemplateVersion,
                    sample_fields: sampleFields,
                });

                if (!active) return;
                setPreviewData(data);
                setValidationData(validation);
                setRequiredFieldsData(requiredFields);
                setPrecheckData(precheck);
                if (data.template_profile && data.template_profile !== previewTemplateProfile) {
                    setPreviewTemplateProfile(data.template_profile);
                }
            } catch (err) {
                if (!active) return;
                setError(toUiErrorMessage(err, t("templates.previewFailed")));
                setPreviewData(null);
                setValidationData(null);
                setRequiredFieldsData(null);
                setPrecheckData(null);
            } finally {
                if (active) {
                    setPreviewingTemplateId(null);
                }
            }
        };
        const timer = setTimeout(() => {
            void run();
        }, 200);
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [previewTemplateId, previewTemplateVersion, previewTemplateProfile, previewMode]);

    const closePreview = () => {
        setPreviewTemplateId(null);
        setPreviewData(null);
        setValidationData(null);
        setRequiredFieldsData(null);
        setPrecheckData(null);
        setPreviewingTemplateId(null);
    };

    const isHighFidelity = previewMode === "high_fidelity";

    const handleModeToggle = () => {
        setPreviewMode((prev) => (prev === "safe" ? "high_fidelity" : "safe"));
    };

    const previewSandbox = isHighFidelity ? "allow-same-origin allow-scripts" : "allow-same-origin";

    const renderPreviewHeader = () => (
        <div className="flex flex-wrap items-center gap-2">
            <Select value={previewTemplateProfile || "__auto__"} onValueChange={(value) => setPreviewTemplateProfile(value === "__auto__" ? "" : value)}>
                <SelectTrigger className="w-[180px]">
                    <SelectValue placeholder="Template Profile" />
                </SelectTrigger>
                <SelectContent>
                    <SelectItem value="__auto__">Auto</SelectItem>
                    {(previewData?.available_profiles?.length
                        ? previewData.available_profiles
                        : []).map((profile) => (
                        <SelectItem key={profile} value={profile}>
                            {profile}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
            <Button type="button" variant={isHighFidelity ? "default" : "outline"} size="sm" onClick={handleModeToggle}>
                {isHighFidelity ? "High Fidelity" : "Safe Mode"}
            </Button>
        </div>
    );

    const renderPreviewFrame = (title: string, srcDoc: string) => (
        <iframe
            title={title}
            sandbox={previewSandbox}
            srcDoc={srcDoc}
            className="w-full h-[480px] rounded border bg-white"
        />
    );

    const previewOpen = !!previewTemplateId;

    const previewLoading = !previewData || previewingTemplateId === previewTemplateId;

    const handlePreviewRequest = (templateId: string, version: number) => {
        setPreviewTemplateId(templateId);
        setPreviewTemplateVersion(version);
        setPreviewTemplateProfile("");
        setPreviewMode("high_fidelity");
        setPreviewData(null);
        setValidationData(null);
        setRequiredFieldsData(null);
        setPrecheckData(null);
        setError(null);
    };

    return (
        <div className="p-4 sm:p-8 space-y-6 sm:space-y-8">
            <div className="space-y-2">
                <h1 className="text-3xl font-bold tracking-tight">{t("templates.title")}</h1>
                <p className="text-muted-foreground">{t("templates.subtitle")}</p>
                <div className="flex items-center gap-2">
                    <Button asChild size="sm" variant="outline" disabled={importing}>
                        <label className="cursor-pointer">
                            {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                            Import Template
                            <input
                                type="file"
                                accept=".json,.kctpl.json"
                                className="hidden"
                                onChange={handleImportFile}
                            />
                        </label>
                    </Button>
                </div>
            </div>

            {error && (
                <div className="text-sm text-red-600">{error}</div>
            )}

            {isLoading ? (
                <div className="text-sm text-muted-foreground">{t("templates.loading")}</div>
            ) : templates.length === 0 ? (
                <div className="text-sm text-muted-foreground">{t("templates.empty")}</div>
            ) : (
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {templates.map((template) => {
                        const isCurrentDefault = userDefaultTemplateId === template.template_id;
                        const isSaving = savingTemplateId === template.template_id;
                        return (
                            <Card key={template.template_id} className="h-full">
                                <CardHeader className="space-y-3">
                                    <div className="flex items-center justify-between gap-2">
                                        <div className="flex items-center gap-2 min-w-0">
                                            <LayoutTemplate className="h-4 w-4 text-sky-600 shrink-0" />
                                            <CardTitle className="text-base truncate">{template.name}</CardTitle>
                                        </div>
                                        {template.is_default && (
                                            <Badge variant="secondary">{t("templates.systemDefault")}</Badge>
                                        )}
                                    </div>
                                    <CardDescription className="line-clamp-2">
                                        {template.description || t("templates.noDescription")}
                                    </CardDescription>
                                </CardHeader>
                                <CardContent className="space-y-3">
                                    <div className="text-xs text-muted-foreground">
                                        {t("templates.version", { version: template.latest_version })}
                                    </div>
                                    <Button
                                        type="button"
                                        className="w-full"
                                        variant={isCurrentDefault ? "secondary" : "outline"}
                                        onClick={() => handleSetDefault(template.template_id, template.latest_version)}
                                        disabled={isSaving}
                                    >
                                        {isSaving ? (
                                            <Loader2 className="h-4 w-4 animate-spin" />
                                        ) : isCurrentDefault ? (
                                            <>
                                                <CheckCircle2 className="h-4 w-4" />
                                                {t("templates.currentDefault")}
                                            </>
                                        ) : (
                                            t("templates.setDefault")
                                        )}
                                    </Button>
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        className="w-full"
                                        onClick={() => handleExportTemplate(template.template_id, template.latest_version)}
                                        disabled={exportingTemplateId === template.template_id}
                                    >
                                        {exportingTemplateId === template.template_id ? (
                                            <Loader2 className="h-4 w-4 animate-spin" />
                                        ) : (
                                            <>
                                                <Download className="h-4 w-4" />
                                                Export
                                            </>
                                        )}
                                    </Button>
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        className="w-full"
                                        onClick={() => { void handlePreviewRequest(template.template_id, template.latest_version); }}
                                        disabled={previewingTemplateId === template.template_id}
                                    >
                                        {previewingTemplateId === template.template_id ? (
                                            <Loader2 className="h-4 w-4 animate-spin" />
                                        ) : (
                                            <>
                                                <Eye className="h-4 w-4" />
                                                {t("common.view")}
                                            </>
                                        )}
                                    </Button>
                                </CardContent>
                            </Card>
                        );
                    })}
                </div>
            )}

            <Dialog open={previewOpen} onOpenChange={(open) => !open && closePreview()}>
                <DialogContent className="max-w-5xl h-[90vh] overflow-hidden flex flex-col">
                    <DialogHeader>
                        <DialogTitle>{t("templates.previewTitle")}</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-3 flex-1 min-h-0 overflow-y-auto pr-1">
                        {renderPreviewHeader()}
                        {previewLoading ? (
                            <div className="h-[520px] flex items-center justify-center text-sm text-muted-foreground">
                                <Loader2 className="h-4 w-4 animate-spin mr-2" />
                                {t("templates.previewLoading")}
                            </div>
                        ) : (
                            <div className="space-y-3">
                            <div className="grid gap-3 md:grid-cols-3">
                                <div className="rounded border p-3 text-sm">
                                    <div className="font-medium">Validation</div>
                                    <div className={validationData?.validation?.ok ? "text-emerald-600 mt-1" : "text-red-600 mt-1"}>
                                        {validationData?.validation?.ok ? "Valid" : "Invalid"}
                                    </div>
                                    {(validationData?.validation?.errors?.length || 0) > 0 && (
                                        <div className="mt-1 text-xs text-muted-foreground">
                                            {validationData?.validation?.errors?.[0]?.message}
                                        </div>
                                    )}
                                </div>
                                <div className="rounded border p-3 text-sm">
                                    <div className="font-medium">Precheck</div>
                                    <div className="mt-1">
                                        Estimated cards: <span className="font-semibold">{precheckData?.card_count ?? "-"}</span>
                                    </div>
                                    <div className="text-xs text-muted-foreground mt-1">
                                        {precheckData?.would_generate_empty ? "Contains empty sample cards." : "No empty sample cards."}
                                    </div>
                                </div>
                                <div className="rounded border p-3 text-sm">
                                    <div className="font-medium">Required Fields</div>
                                    <div className="mt-1 text-xs text-muted-foreground">
                                        {requiredFieldsData?.field_names?.join(", ") || "-"}
                                    </div>
                                </div>
                            </div>

                            {requiredFieldsData?.card_templates && requiredFieldsData.card_templates.length > 0 && (
                                <div className="rounded border p-3 text-xs text-muted-foreground space-y-1">
                                    {requiredFieldsData.card_templates.map((item) => (
                                        <div key={item.template_ord}>
                                            Card {item.template_ord + 1} ({item.mode}): {item.required_field_names.join(", ") || "-"}
                                        </div>
                                    ))}
                                </div>
                            )}

                            {previewData.warnings && previewData.warnings.length > 0 && (
                                <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
                                    {previewData.warnings.join(" ")}
                                </div>
                            )}
                            {previewData.media_tags && previewData.media_tags.length > 0 && (
                                <div className="rounded border p-3 text-xs text-muted-foreground">
                                    <div className="font-medium text-foreground">Media Tags</div>
                                    <div className="mt-1 break-all">{previewData.media_tags.join(", ")}</div>
                                </div>
                            )}
                            <Tabs defaultValue="front">
                                <TabsList>
                                    <TabsTrigger value="front">{t("templates.previewFront")}</TabsTrigger>
                                    <TabsTrigger value="back">{t("templates.previewBack")}</TabsTrigger>
                                </TabsList>
                                <TabsContent value="front" className="mt-3">
                                    {renderPreviewFrame("template-front-preview", previewData.front_document)}
                                </TabsContent>
                                <TabsContent value="back" className="mt-3">
                                    {renderPreviewFrame("template-back-preview", previewData.back_document)}
                                </TabsContent>
                            </Tabs>
                            </div>
                        )}
                    </div>
                </DialogContent>
            </Dialog>
        </div>
    );
}
