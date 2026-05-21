"use client";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { FileUploadAPI } from "@/lib/file-upload/api";
import { DEFAULT_UPLOAD_CONFIG, FileUploadConfig, UploadedFile } from "@/lib/file-upload/types";
import { FileValidator } from "@/lib/file-upload/validation";
import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";
import { AlertCircle, Check, Eye, File, Image as ImageIcon, Loader2, Trash2, Upload, X } from "lucide-react";
import { useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";

export interface FileUploadHandle {
  uploadPendingFiles: () => Promise<string[]>;
  clearFiles: () => void;
}

const EMPTY_CONFIG: Partial<FileUploadConfig> = {};

interface FileUploadProps {
  sessionId?: string;
  onFilesChange?: (files: UploadedFile[]) => void;
  onUploadComplete?: (fileIds: string[]) => void;
  config?: Partial<FileUploadConfig>;
  className?: string;
  disabled?: boolean;
  maxHeight?: string;
  showManualUploadButton?: boolean;
  ref?: React.Ref<FileUploadHandle>;
}

export function FileUpload({
  sessionId,
  onFilesChange,
  onUploadComplete,
  config = EMPTY_CONFIG,
  className,
  disabled = false,
  maxHeight = "300px",
  showManualUploadButton = true,
  ref,
}: FileUploadProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dropZoneRef = useRef<HTMLDivElement>(null);
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadingCount, setUploadingCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const { t } = useTranslation();
  const uploadConfig = useMemo(() => ({ ...DEFAULT_UPLOAD_CONFIG, ...config }), [config]);
  const validator = useMemo(() => new FileValidator(uploadConfig, t), [uploadConfig, t]);
  const uploadAPI = useMemo(() => new FileUploadAPI(), []);

  // Notify parent when files change
  useEffect(() => {
    onFilesChange?.(files);
  }, [files, onFilesChange]);

  const handleFileSelect = useCallback((selectedFiles: FileList | File[]) => {
    setError(null);

    const fileArray = Array.from(selectedFiles);
    const existingFiles = files.map((item) => item.file);
    const validation = validator.validateFiles(fileArray, existingFiles);

    if (!validation.isValid) {
      setError(validation.errors.join("\n"));
      return;
    }

    const newUploadedFiles: UploadedFile[] = fileArray.map((file) => ({
      id: crypto.randomUUID(),
      file,
      name: file.name,
      size: file.size,
      type: file.type,
      uploadProgress: 0,
      status: "pending",
    }));

    setFiles((prev) => [...prev, ...newUploadedFiles]);
  }, [files, validator]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    if (disabled) return;

    const droppedFiles = e.dataTransfer.files;
    if (droppedFiles.length > 0) {
      handleFileSelect(droppedFiles);
    }
  }, [disabled, handleFileSelect]);

  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFileSelect(e.target.files);
      // Reset input to allow selecting same file again
      e.target.value = "";
    }
  }, [handleFileSelect]);

  const removeFile = useCallback((fileId: string) => {
    const target = files.find((file) => file.id === fileId);
    setFiles((prev) => prev.filter((file) => file.id !== fileId));
    setError(null);
    if (target?.serverFileId) {
      void uploadAPI.deleteFile(target.serverFileId).catch((deleteError) => {
        console.error("[FileUpload] Failed to delete uploaded file:", deleteError);
      });
    }
  }, [files, uploadAPI]);

  const uploadFile = useCallback(async (uploadedFile: UploadedFile) => {
    setFiles((prev) =>
      prev.map((file) =>
        file.id === uploadedFile.id ? { ...file, status: "uploading" } : file
      )
    );

    try {
      const response = await uploadAPI.uploadFile(
        uploadedFile.file,
        sessionId,
        (progress) => {
          setFiles((prev) =>
            prev.map((file) =>
              file.id === uploadedFile.id ? { ...file, uploadProgress: progress } : file
            )
          );
        }
      );

      setFiles((prev) =>
        prev.map((file) =>
          file.id === uploadedFile.id
            ? {
                ...file,
                serverFileId: response.file_id,
                status: "uploaded",
                uploadProgress: 100,
                previewUrl: response.preview_url,
                uploadedAt: new Date(response.uploaded_at),
              }
            : file
        )
      );

      return response.file_id;
    } catch (error) {
      setFiles((prev) =>
        prev.map((file) =>
          file.id === uploadedFile.id
            ? {
                ...file,
                status: "error",
                error: error instanceof Error ? error.message : t("fileUpload.uploadFailed"),
              }
            : file
        )
      );
      throw error;
    }
  }, [sessionId, uploadAPI]);

  const uploadAllFiles = useCallback(async (): Promise<string[]> => {
    const pendingFiles = files.filter((file) => file.status === "pending");
    if (pendingFiles.length === 0) return [];

    setError(null);
    setUploadingCount(pendingFiles.length);

    const uploadedFileIds: string[] = [];
    const errors: string[] = [];

    // Upload files with concurrency control
    const concurrentUploads = uploadConfig.concurrentUploads || 3;
    const chunks = [];
    for (let i = 0; i < pendingFiles.length; i += concurrentUploads) {
      chunks.push(pendingFiles.slice(i, i + concurrentUploads));
    }

    for (const chunk of chunks) {
      const promises = chunk.map(async (file) => {
        try {
          const fileId = await uploadFile(file);
          uploadedFileIds.push(fileId);
        } catch (error) {
          errors.push(`${file.name}: ${error instanceof Error ? error.message : t("fileUpload.uploadFailed")}`);
        } finally {
          setUploadingCount((prev) => prev - 1);
        }
      });

      await Promise.all(promises);
    }

    if (errors.length > 0) {
      setError(errors.join("\n"));
    }

    if (uploadedFileIds.length > 0) {
      onUploadComplete?.(uploadedFileIds);
    }

    if (uploadedFileIds.length === 0 && pendingFiles.length > 0) {
      throw new Error(errors.join("\n") || t("fileUpload.uploadFailed"));
    }

    return uploadedFileIds;
  }, [files, uploadFile, uploadConfig.concurrentUploads, onUploadComplete]);

  useEffect(() => {
    if (showManualUploadButton || disabled || uploadingCount > 0) {
      return;
    }
    if (!files.some((file) => file.status === "pending")) {
      return;
    }
    void uploadAllFiles().catch(() => {
      // Error is displayed via component state.
    });
  }, [showManualUploadButton, disabled, uploadingCount, files, uploadAllFiles]);

  const retryFile = useCallback(async (fileId: string) => {
    const fileToRetry = files.find((file) => file.id === fileId);
    if (!fileToRetry) return;

    try {
      await uploadFile(fileToRetry);
    } catch {
      // Error is already handled in uploadFile
    }
  }, [files, uploadFile]);

  const clearAllFiles = useCallback(() => {
    if (uploadingCount > 0 || files.some((file) => file.status === "uploading")) {
      return;
    }
    const uploadedFileIds = files
      .map((file) => file.serverFileId)
      .filter((fileId): fileId is string => !!fileId);
    setFiles([]);
    setError(null);
    uploadedFileIds.forEach((fileId) => {
      void uploadAPI.deleteFile(fileId).catch((deleteError) => {
        console.error("[FileUpload] Failed to delete uploaded file:", deleteError);
      });
    });
  }, [files, uploadAPI, uploadingCount]);

  useImperativeHandle(ref, () => ({
    uploadPendingFiles: uploadAllFiles,
    clearFiles: clearAllFiles,
  }), [uploadAllFiles, clearAllFiles]);

  const totalSize = files.reduce((sum, file) => sum + file.size, 0);
  const uploadedFiles = files.filter((file) => file.status === "uploaded");
  const pendingFiles = files.filter((file) => file.status === "pending");
  const errorFiles = files.filter((file) => file.status === "error");
  const uploadingFiles = files.filter((file) => file.status === "uploading");

  const canUpload = pendingFiles.length > 0 && uploadingCount === 0;
  const isUploading = uploadingCount > 0;

  return (
    <div className={cn("space-y-4", className)} data-kc-file-upload-root="true">
      {/* Drop zone */}
      <div
        ref={dropZoneRef}
        className={cn(
          "border border-dashed rounded-lg p-4 text-center transition-colors",
          isDragging
            ? "border-primary bg-primary/5"
            : "border-muted-foreground/25 hover:border-muted-foreground/50",
          disabled && "opacity-50 cursor-not-allowed"
        )}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => !disabled && fileInputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            !disabled && fileInputRef.current?.click();
          }
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFileInputChange}
          className="hidden"
          disabled={disabled}
          accept={uploadConfig.allowedTypes.join(",")}
        />

        <div className="flex flex-col items-center justify-center gap-2">
          <div className="p-2 rounded-full bg-muted">
            <Upload className="size-4 text-muted-foreground" />
          </div>

          <div className="space-y-1">
            <p className="text-sm font-medium">
              {t("fileUpload.dropFilesHere")}{" "}
              <span className="text-primary hover:underline cursor-pointer">{t("fileUpload.clickToBrowse")}</span>
            </p>
            <p className="text-xs text-muted-foreground">
              {t("fileUpload.supportedFormats", { formats: uploadConfig.allowedTypes.map((type) => type.split("/")[1]).join(", ") })}
              <br />
              {t("fileUpload.fileLimits", { maxSize: validator.formatFileSize(uploadConfig.maxFileSize), maxFiles: uploadConfig.maxFiles })}
            </p>
          </div>
        </div>
      </div>

      {/* Error message */}
      {error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-destructive/10 text-destructive">
          <AlertCircle className="size-4 mt-0.5 shrink-0" />
          <div className="flex-1">
            <p className="text-sm font-medium">{t("fileUpload.uploadError")}</p>
            <p className="text-sm whitespace-pre-wrap">{error}</p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-6 shrink-0"
            onClick={() => setError(null)}
          >
            <X className="size-4" />
          </Button>
        </div>
      )}

      {/* File list */}
      {files.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="font-medium">
                {t("fileUpload.filesSelected", { count: files.length, size: validator.formatFileSize(totalSize) })}
              </span>
              {isUploading && (
                <span className="inline-flex items-center gap-1 text-sm text-muted-foreground">
                  <Loader2 className="size-3 animate-spin" />
                  {t("fileUpload.uploading", { count: uploadingCount })}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {showManualUploadButton && pendingFiles.length > 0 && (
                <Button
                  type="button"
                  size="sm"
                  onClick={uploadAllFiles}
                  disabled={!canUpload || disabled}
                  className="gap-2"
                >
                  {isUploading ? (
                    <>
                      <Loader2 className="size-3 animate-spin" />
                      {t("fileUpload.uploadingShort")}
                    </>
                  ) : (
                    <>
                      <Upload className="size-3" />
                      {t("fileUpload.uploadAll")}
                    </>
                  )}
                </Button>
              )}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={clearAllFiles}
                disabled={disabled || isUploading}
              >
                {t("fileUpload.clearAll")}
              </Button>
            </div>
          </div>

          <div
            className="space-y-2 overflow-y-auto"
            style={{ maxHeight }}
          >
            {files.map((file) => (
              <div
                key={file.id}
                className="flex items-center gap-3 p-3 rounded-lg border"
              >
                <div className="p-2 rounded-md bg-muted">
                  {file.type.startsWith("image/") ? (
                    <ImageIcon className="size-5" />
                  ) : (
                    <File className="size-5" />
                  )}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-medium truncate" title={file.name}>
                      {file.name}
                    </p>
                    <span className="text-sm text-muted-foreground shrink-0">
                      {validator.formatFileSize(file.size)}
                    </span>
                  </div>

                  <div className="mt-1">
                    {file.status === "uploading" && (
                      <div className="space-y-1">
                        <Progress value={file.uploadProgress} className="h-1.5" />
                        <p className="text-xs text-muted-foreground">
                          {file.uploadProgress.toFixed(0)}%
                        </p>
                      </div>
                    )}

                    {file.status === "uploaded" && (
                      <div className="flex items-center gap-1 text-xs text-green-600">
                        <Check className="size-3" />
                        <span>{t("fileUpload.uploaded")}</span>
                        {file.previewUrl && (
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="size-5 ml-1"
                            onClick={() => window.open(file.previewUrl, "_blank")}
                          >
                            <Eye className="size-3" />
                          </Button>
                        )}
                      </div>
                    )}

                    {file.status === "error" && (
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-1 text-xs text-destructive">
                          <AlertCircle className="size-3" />
                          <span>{file.error || t("fileUpload.uploadFailed")}</span>
                        </div>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-6 text-xs"
                          onClick={() => retryFile(file.id)}
                          disabled={disabled}
                        >
                          {t("fileUpload.retry")}
                        </Button>
                      </div>
                    )}

                    {file.status === "pending" && (
                      <p className="text-xs text-muted-foreground">
                        {showManualUploadButton ? t("fileUpload.waitingUpload") : t("fileUpload.pendingSend")}
                      </p>
                    )}
                  </div>
                </div>

                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-8 shrink-0"
                  onClick={() => removeFile(file.id)}
                  disabled={disabled || file.status === "uploading"}
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            ))}
          </div>

          {/* Summary */}
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <div className="flex items-center gap-4">
              <span>{showManualUploadButton ? t("fileUpload.pendingUpload") : t("fileUpload.pendingSend")}: {pendingFiles.length}</span>
              <span>{t("fileUpload.uploadingLabel")}: {uploadingFiles.length}</span>
              <span>{t("fileUpload.uploaded")}: {uploadedFiles.length}</span>
              {errorFiles.length > 0 && (
                <span className="text-destructive">{t("fileUpload.failed")}: {errorFiles.length}</span>
              )}
            </div>
            <span>{t("fileUpload.totalSize", { size: validator.formatFileSize(totalSize) })}</span>
          </div>
        </div>
      )}
    </div>
  );
}
