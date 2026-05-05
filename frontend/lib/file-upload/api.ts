import { UploadResponse, TaskWithFilesRequest } from './types';

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_PATH || '').replace(/\/$/, '');

function getAuthHeaders(): Record<string, string> {
  return {};
}

/**
 * Retry with exponential backoff.
 */
async function withRetry<T>(
  fn: () => Promise<T>,
  maxRetries: number = 3,
  baseDelay: number = 500
): Promise<T> {
  let lastError: Error | null = null;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
      if (attempt < maxRetries) {
        const delay = baseDelay * Math.pow(2, attempt);
        await new Promise(resolve => setTimeout(resolve, delay));
      }
    }
  }
  throw lastError;
}

export class FileUploadAPI {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  /**
   * Upload file through same-origin backend endpoints.
   * 1. init upload session
   * 2. upload chunks
   * 3. complete upload and get file_id
   */
  async uploadFile(
    file: File,
    sessionId?: string,
    onProgress?: (progress: number) => void,
  ): Promise<UploadResponse> {
    const chunkSize = 5 * 1024 * 1024;
    const chunkCount = Math.max(1, Math.ceil(file.size / chunkSize));
    const initResponse = await withRetry(() => this.initUpload(file.name, chunkCount, sessionId));
    const uploadId = initResponse.upload_id;

    let uploadedBytes = 0;
    for (let index = 0; index < chunkCount; index += 1) {
      const start = index * chunkSize;
      const end = Math.min(file.size, start + chunkSize);
      const chunk = file.slice(start, end);
      await withRetry(() => this.uploadChunk(uploadId, index, chunk));
      uploadedBytes += chunk.size;
      if (onProgress) {
        onProgress((uploadedBytes / file.size) * 100);
      }
    }

    const completion = await withRetry(() => this.completeUpload(uploadId));
    const fileId = String(completion.file_id || "").trim();
    if (!fileId) {
      throw new Error("Upload completed but file_id is missing");
    }

    return {
      file_id: fileId,
      filename: file.name,
      size: file.size,
      mime_type: file.type,
      uploaded_at: new Date().toISOString(),
    };
  }

  private async initUpload(filename: string, chunkCount: number, sessionId?: string): Promise<{ upload_id: string }> {
    const response = await fetch(`${this.baseUrl}/api/v1/files/upload/init`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      credentials: 'include',
      body: JSON.stringify({
        filename,
        chunk_count: chunkCount,
        session_id: sessionId,
      }),
    });
    if (!response.ok) {
      throw new Error(`Failed to initialize upload: ${response.status} ${response.statusText}`);
    }
    return response.json();
  }

  private async uploadChunk(uploadId: string, chunkIndex: number, chunk: Blob): Promise<void> {
    const response = await fetch(`${this.baseUrl}/api/v1/files/upload/chunk/${encodeURIComponent(uploadId)}/${chunkIndex}`, {
      method: 'POST',
      headers: getAuthHeaders(),
      credentials: 'include',
      body: chunk,
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Failed to upload chunk ${chunkIndex}: ${response.status} ${response.statusText} - ${errorText}`);
    }
  }

  private async completeUpload(uploadId: string): Promise<{ file_id: string }> {
    const response = await fetch(`${this.baseUrl}/api/v1/files/upload/complete/${encodeURIComponent(uploadId)}`, {
      method: 'POST',
      headers: getAuthHeaders(),
      credentials: 'include',
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Failed to complete upload: ${response.status} ${response.statusText} - ${errorText}`);
    }
    return response.json();
  }

  async submitTaskWithFiles(request: TaskWithFilesRequest) {
    const taskType = request.task_type || "main";
    const input: Record<string, unknown> = {
      session_id: request.session_id,
      file_ids: request.file_ids,
      attachments: request.attachments,
      research_strategy: request.research_strategy,
    };
    if (taskType === "card_template") {
      const templateId = request.template_id || (typeof request.context?.template_id === "string" ? request.context.template_id : "");
      input.template_id = templateId;
      input.variables = request.context;
    } else {
      input.context = request.context;
    }

    const payload = {
      task_type: taskType,
      query: request.query,
      input,
    };

    const response = await fetch(`${this.baseUrl}/api/v1/tasks`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      credentials: 'include',
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Failed to submit task with files: ${response.statusText} - ${errorText}`);
    }

    return response.json();
  }

  async deleteFile(fileId: string): Promise<void> {
    // Same-origin upload flow currently has no delete endpoint.
    // Keep this method idempotent so callers can perform cleanup safely.
    void fileId;
  }

  async getFilePreview(fileId: string): Promise<string> {
    const response = await fetch(`${this.baseUrl}/api/v1/files/${fileId}/preview`, {
      headers: getAuthHeaders(),
      credentials: 'include',
    });

    if (!response.ok) {
      throw new Error(`Failed to get file preview: ${response.statusText}`);
    }

    const data = await response.json();
    return data.preview_url;
  }
}
