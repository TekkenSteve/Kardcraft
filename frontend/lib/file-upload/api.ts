import { UploadResponse, TaskWithFilesRequest, PresignedUrlResponse, ConfirmUploadResponse } from './types';

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_PATH || '').replace(/\/$/, '');
const FILE_STORAGE_URL = (
  process.env.NEXT_PUBLIC_FILE_STORAGE_URL ||
  `${API_BASE_URL}/api/v1/files` ||
  '/api/v1/files'
).replace(/\/$/, '');

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
  private fileStorageUrl: string;

  constructor(baseUrl: string = API_BASE_URL, fileStorageUrl: string = FILE_STORAGE_URL) {
    this.baseUrl = baseUrl;
    this.fileStorageUrl = fileStorageUrl;
  }

  /**
   * Upload file using presigned URL flow:
   * 1. Get presigned URL from file-storage
   * 2. PUT file directly to MinIO
   * 3. Confirm upload with file-storage
   */
  async uploadFile(
    file: File,
    sessionId?: string,
    onProgress?: (progress: number) => void,
  ): Promise<UploadResponse> {
    await this.healthCheck();

    // Step 1: Get presigned URL
    const presignedData = await withRetry(() =>
      this.getPresignedUrl(file.name, file.type, sessionId)
    );

    // Step 2: Upload directly to MinIO using presigned URL
    await withRetry(() =>
      this.uploadToPresignedUrl(presignedData.url, file, onProgress)
    );

    // Step 3: Confirm upload
    const confirmation = await withRetry(() =>
      this.confirmUpload(presignedData.file_id, presignedData.key, file.type)
    );

    if (!confirmation.success) {
      throw new Error(confirmation.message || 'Upload confirmation failed');
    }

    return {
      file_id: presignedData.file_id,
      filename: file.name,
      size: file.size,
      mime_type: file.type,
      uploaded_at: new Date().toISOString(),
    };
  }

  /**
   * Get presigned URL from file-storage service.
   */
  private async getPresignedUrl(
    filename: string,
    contentType: string,
    sessionId?: string
  ): Promise<PresignedUrlResponse> {
    const params = new URLSearchParams({
      filename,
      content_type: contentType,
    });
    if (sessionId) {
      params.append('session_id', sessionId);
    }

    const response = await fetch(`${this.fileStorageUrl}/presigned-url?${params}`, {
      method: 'GET',
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Failed to get presigned URL: ${response.statusText} - ${errorText}`);
    }

    return response.json();
  }

  /**
   * Upload file directly to MinIO using presigned URL.
   */
  private async uploadToPresignedUrl(
    url: string,
    file: File,
    onProgress?: (progress: number) => void
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();

      xhr.upload.addEventListener('progress', (event) => {
        if (event.lengthComputable && onProgress) {
          const progress = (event.loaded / event.total) * 100;
          onProgress(progress);
        }
      });

      xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve();
        } else {
          reject(new Error(`Upload failed: ${xhr.statusText}`));
        }
      });

      xhr.addEventListener('error', () => {
        reject(new Error('Network error during upload'));
      });

      xhr.addEventListener('abort', () => {
        reject(new Error('Upload cancelled'));
      });

      xhr.open('PUT', url);
      xhr.setRequestHeader('Content-Type', file.type);
      xhr.send(file);
    });
  }

  /**
   * Confirm upload completion with file-storage.
   */
  private async confirmUpload(
    fileId: string,
    key: string,
    contentType: string
  ): Promise<ConfirmUploadResponse> {
    const response = await fetch(`${this.fileStorageUrl}/confirm-upload`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      body: JSON.stringify({
        file_id: fileId,
        key: key,
        content_type: contentType,
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Upload confirmation failed: ${response.statusText} - ${errorText}`);
    }

    return response.json();
  }

  async healthCheck(): Promise<void> {
    const response = await fetch(`${this.fileStorageUrl}/health`, {
      method: 'GET',
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      throw new Error(`文件服务不可用: ${response.status} ${response.statusText}`);
    }
  }

  async submitTaskWithFiles(request: TaskWithFilesRequest) {
    const payload = {
      task_type: request.task_type || "main",
      query: request.query,
      input: {
        session_id: request.session_id,
        file_ids: request.file_ids,
        attachments: request.attachments,
        context: request.context,
        research_strategy: request.research_strategy,
      },
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
    const response = await fetch(`${this.fileStorageUrl}/${fileId}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });

    if (response.status === 404) {
      // Treat already-deleted/non-existent files as a successful cleanup.
      return;
    }

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Failed to delete file: ${response.status} ${response.statusText} - ${errorText}`);
    }
  }

  async getFilePreview(fileId: string): Promise<string> {
    const response = await fetch(`${this.baseUrl}/api/v1/files/${fileId}/preview`, {
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      throw new Error(`Failed to get file preview: ${response.statusText}`);
    }

    const data = await response.json();
    return data.preview_url;
  }
}
