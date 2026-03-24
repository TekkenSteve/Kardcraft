import { FileValidationResult, DEFAULT_UPLOAD_CONFIG, FileUploadConfig } from './types';

/**
 * Magic number signatures for common file types.
 * Maps MIME types to arrays of possible byte signatures.
 */
const MAGIC_NUMBERS: Record<string, number[][]> = {
  // Images
  'image/jpeg': [[0xFF, 0xD8, 0xFF]],
  'image/png': [[0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]],
  'image/gif': [[0x47, 0x49, 0x46, 0x38, 0x37, 0x61], [0x47, 0x49, 0x46, 0x38, 0x39, 0x61]], // GIF87a, GIF89a
  'image/webp': [[0x52, 0x49, 0x46, 0x46]], // RIFF (followed by WEBP at offset 8)
  'image/bmp': [[0x42, 0x4D]], // BM
  // Documents
  'application/pdf': [[0x25, 0x50, 0x44, 0x46]], // %PDF
  'application/zip': [[0x50, 0x4B, 0x03, 0x04], [0x50, 0x4B, 0x05, 0x06], [0x50, 0x4B, 0x07, 0x08]], // PK variants
  'application/x-rar-compressed': [[0x52, 0x61, 0x72, 0x21, 0x1A, 0x07]], // Rar!
  'application/x-7z-compressed': [[0x37, 0x7A, 0xBC, 0xAF, 0x27, 0x1C]], // 7z
  // Office documents (ZIP-based)
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': [[0x50, 0x4B, 0x03, 0x04]], // docx
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': [[0x50, 0x4B, 0x03, 0x04]], // xlsx
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': [[0x50, 0x4B, 0x03, 0x04]], // pptx
};

/**
 * Extension to MIME type mapping for fallback validation.
 */
const EXTENSION_TO_MIME: Record<string, string> = {
  'jpg': 'image/jpeg',
  'jpeg': 'image/jpeg',
  'png': 'image/png',
  'gif': 'image/gif',
  'webp': 'image/webp',
  'bmp': 'image/bmp',
  'pdf': 'application/pdf',
  'zip': 'application/zip',
  'rar': 'application/x-rar-compressed',
  '7z': 'application/x-7z-compressed',
  'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
};

export class FileValidator {
  private config: FileUploadConfig;

  constructor(config: FileUploadConfig = DEFAULT_UPLOAD_CONFIG) {
    this.config = config;
  }

  validateFile(file: File): FileValidationResult {
    const errors: string[] = [];

    // Check file size
    if (file.size > this.config.maxFileSize) {
      errors.push(`文件太大: ${this.formatFileSize(file.size)} (最大 ${this.formatFileSize(this.config.maxFileSize)})`);
    }

    // Check file type
    if (!this.isFileTypeAllowed(file.type, file.name)) {
      errors.push(`不支持的文件类型: ${file.type || '未知类型'}`);
    }

    // Check file name (basic security)
    if (!this.isFileNameSafe(file.name)) {
      errors.push('文件名包含不安全字符');
    }

    return {
      isValid: errors.length === 0,
      errors,
    };
  }

  /**
   * Validates file content against magic number signatures.
   * This is an async operation as it requires reading file bytes.
   * @param file The file to validate
   * @returns Promise<FileValidationResult> with validation result
   */
  async validateMagicNumber(file: File): Promise<FileValidationResult> {
    const errors: string[] = [];

    // Get the expected MIME type from extension
    const extension = this.getFileExtension(file.name).toLowerCase();
    const expectedMime = EXTENSION_TO_MIME[extension];

    // If we don't have a magic number for this type, skip validation
    if (!expectedMime || !MAGIC_NUMBERS[expectedMime]) {
      return { isValid: true, errors: [] };
    }

    const signatures = MAGIC_NUMBERS[expectedMime];
    const maxBytes = Math.max(...signatures.map(s => s.length));

    try {
      // Read the first N bytes of the file
      const header = await this.readFileHeader(file, maxBytes);

      // Check if any signature matches
      const matches = signatures.some(signature =>
        signature.every((byte, index) => header[index] === byte)
      );

      if (!matches) {
        errors.push(`文件内容与扩展名不匹配: 检测到的内容类型与 .${extension} 不一致`);
      }
    } catch {
      // If we can't read the file, we can't validate - return warning
      errors.push('无法验证文件内容');
    }

    return {
      isValid: errors.length === 0,
      errors,
    };
  }

  /**
   * Reads the first N bytes of a file.
   */
  private readFileHeader(file: File, bytes: number): Promise<Uint8Array> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      const blob = file.slice(0, bytes);

      reader.onload = () => {
        if (reader.result instanceof ArrayBuffer) {
          resolve(new Uint8Array(reader.result));
        } else {
          reject(new Error('Failed to read file as ArrayBuffer'));
        }
      };

      reader.onerror = () => reject(reader.error);
      reader.readAsArrayBuffer(blob);
    });
  }

  validateFiles(files: File[], existingFiles: File[] = []): FileValidationResult {
    const errors: string[] = [];

    // Check total number of files
    const totalFiles = files.length + existingFiles.length;
    if (totalFiles > this.config.maxFiles) {
      errors.push(`文件数量过多: ${totalFiles} (最多 ${this.config.maxFiles} 个)`);
    }

    // Check total size
    const totalSize = [...files, ...existingFiles].reduce((sum, file) => sum + file.size, 0);
    if (totalSize > this.config.maxTotalSize) {
      errors.push(`总文件大小过大: ${this.formatFileSize(totalSize)} (最大 ${this.formatFileSize(this.config.maxTotalSize)})`);
    }

    // Validate each file
    for (const file of files) {
      const fileValidation = this.validateFile(file);
      if (!fileValidation.isValid) {
        errors.push(`${file.name}: ${fileValidation.errors.join(', ')}`);
      }
    }

    return {
      isValid: errors.length === 0,
      errors,
    };
  }

  private isFileTypeAllowed(mimeType: string, fileName: string): boolean {
    // If no mime type, check by extension
    if (!mimeType || mimeType === 'application/octet-stream') {
      const extension = this.getFileExtension(fileName);
      return this.isExtensionAllowed(extension);
    }

    // Check by mime type
    return this.config.allowedTypes.includes(mimeType);
  }

  private isExtensionAllowed(extension: string): boolean {
    const allowedExtensions = [
      // Images
      'jpg', 'jpeg', 'png', 'gif', 'webp', 'svg',
      // Documents
      'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
      'txt', 'csv', 'md',
      // Archives
      'zip', 'rar', '7z',
      // JSON
      'json',
    ];
    return allowedExtensions.includes(extension.toLowerCase());
  }

  private getFileExtension(fileName: string): string {
    return fileName.split('.').pop()?.toLowerCase() || '';
  }

  private isFileNameSafe(fileName: string): boolean {
    // Prevent path traversal and other unsafe patterns
    const unsafePatterns = [
      /\.\.\//, // Directory traversal
      /\/\//,   // Double slash
      /\\/,     // Backslash
      /^\s*$/,  // Empty or whitespace only
      /[<>:"|?*]/, // Windows reserved characters
    ];

    return !unsafePatterns.some(pattern => pattern.test(fileName));
  }

  private formatFileSize(bytes: number): string {
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let unitIndex = 0;

    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex++;
    }

    return `${size.toFixed(1)} ${units[unitIndex]}`;
  }

  // Helper to get file icon based on type
  static getFileIcon(fileType: string): string {
    if (fileType.startsWith('image/')) return '🖼️';
    if (fileType === 'application/pdf') return '📄';
    if (fileType.includes('word') || fileType.includes('document')) return '📝';
    if (fileType.includes('excel') || fileType.includes('spreadsheet')) return '📊';
    if (fileType.includes('powerpoint') || fileType.includes('presentation')) return '📽️';
    if (fileType === 'text/plain' || fileType === 'text/markdown') return '📃';
    if (fileType === 'text/csv') return '📈';
    if (fileType === 'application/json') return '{}';
    if (fileType.includes('zip') || fileType.includes('rar') || fileType.includes('7z')) return '📦';
    return '📎';
  }

  // Helper to check if file is previewable
  static isPreviewable(fileType: string): boolean {
    const previewableTypes = [
      'image/jpeg',
      'image/png',
      'image/gif',
      'image/webp',
      'image/svg+xml',
      'application/pdf',
      'text/plain',
      'text/markdown',
      'text/csv',
      'application/json',
    ];
    return previewableTypes.includes(fileType);
  }
}