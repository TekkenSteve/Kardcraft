export interface UploadedFile {
  id: string;
  file: File;
  serverFileId?: string;
  name: string;
  size: number;
  type: string;
  previewUrl?: string;
  uploadProgress: number;
  status: 'pending' | 'uploading' | 'uploaded' | 'error';
  error?: string;
  uploadedAt?: Date;
}

export interface FileUploadConfig {
  maxFileSize: number; // bytes
  maxTotalSize: number; // bytes
  maxFiles: number;
  allowedTypes: string[];
  chunkSize?: number; // bytes for chunked upload
  concurrentUploads?: number;
}

export const DEFAULT_UPLOAD_CONFIG: FileUploadConfig = {
  maxFileSize: 50 * 1024 * 1024, // 50MB
  maxTotalSize: 200 * 1024 * 1024, // 200MB
  maxFiles: 10,
  allowedTypes: [
    // Images
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
    'image/svg+xml',
    // Documents
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'text/plain',
    'text/csv',
    'text/markdown',
    // Archives
    'application/zip',
    'application/x-rar-compressed',
    'application/x-7z-compressed',
    // JSON
    'application/json',
  ],
  chunkSize: 5 * 1024 * 1024, // 5MB chunks
  concurrentUploads: 3,
};

export interface FileValidationResult {
  isValid: boolean;
  errors: string[];
}

export interface UploadResponse {
  file_id: string;
  filename: string;
  size: number;
  mime_type: string;
  preview_url?: string;
  uploaded_at: string;
}

export interface TaskWithFilesRequest {
  query: string;
  task_type?: string;
  session_id?: string;
  file_ids: string[];
  attachments?: Array<{
    file_id: string;
    filename: string;
    size: number;
    mime_type: string;
  }>;
  context?: Record<string, unknown>;
  research_strategy?: 'quick' | 'standard' | 'deep' | 'academic';
}

/**
 * Response from presigned URL endpoint.
 */
export interface PresignedUrlResponse {
  url: string;
  file_id: string;
  expires_at: string;
  key: string;
}

/**
 * Request to confirm upload completion.
 */
export interface ConfirmUploadRequest {
  file_id: string;
  key: string;
  etag?: string;
  content_type?: string;
}

/**
 * Response after confirming upload.
 */
export interface ConfirmUploadResponse {
  success: boolean;
  file_id: string;
  message?: string;
  validated: boolean;
}
