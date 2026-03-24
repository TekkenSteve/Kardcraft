package middleware

import (
	"context"
	"io"
	"time"

	"github.com/sirupsen/logrus"
	"file-storage/internal/types"
)

// AuditMiddleware provides audit logging for storage operations
type AuditMiddleware struct {
	logger *logrus.Logger
}

// NewAuditMiddleware creates a new audit middleware
func NewAuditMiddleware(logger *logrus.Logger) *AuditMiddleware {
	return &AuditMiddleware{
		logger: logger,
	}
}

// Wrap wraps a storage instance with audit logging
func (a *AuditMiddleware) Wrap(s types.Storage) types.Storage {
	return &auditStorage{
		StorageWrapper: NewStorageWrapper(s),
		logger:         a.logger,
	}
}

type auditStorage struct {
	*StorageWrapper
	logger *logrus.Logger
}

// Upload logs upload operations
func (a *auditStorage) Upload(ctx context.Context, key string, reader io.Reader, metadata *types.FileMetadata) error {
	start := time.Now()
	err := a.StorageWrapper.Upload(ctx, key, reader, metadata)
	duration := time.Since(start)

	fields := logrus.Fields{
		"operation": "upload",
		"key":       key,
		"duration":  duration,
	}

	if metadata != nil {
		fields["content_type"] = metadata.ContentType
		fields["content_length"] = metadata.ContentLength
	}

	if err != nil {
		fields["error"] = err.Error()
		a.logger.WithFields(fields).Error("Upload failed")
	} else {
		a.logger.WithFields(fields).Info("Upload completed")
	}

	return err
}

// Download logs download operations
func (a *auditStorage) Download(ctx context.Context, key string) (io.ReadCloser, *types.FileMetadata, error) {
	start := time.Now()
	reader, metadata, err := a.StorageWrapper.Download(ctx, key)
	duration := time.Since(start)

	fields := logrus.Fields{
		"operation": "download",
		"key":       key,
		"duration":  duration,
	}

	if metadata != nil {
		fields["content_type"] = metadata.ContentType
		fields["content_length"] = metadata.ContentLength
	}

	if err != nil {
		fields["error"] = err.Error()
		a.logger.WithFields(fields).Error("Download failed")
	} else {
		a.logger.WithFields(fields).Info("Download completed")
	}

	return reader, metadata, err
}

// Delete logs delete operations
func (a *auditStorage) Delete(ctx context.Context, key string) error {
	start := time.Now()
	err := a.StorageWrapper.Delete(ctx, key)
	duration := time.Since(start)

	fields := logrus.Fields{
		"operation": "delete",
		"key":       key,
		"duration":  duration,
	}

	if err != nil {
		fields["error"] = err.Error()
		a.logger.WithFields(fields).Error("Delete failed")
	} else {
		a.logger.WithFields(fields).Info("Delete completed")
	}

	return err
}

// List logs list operations
func (a *auditStorage) List(ctx context.Context, prefix string, limit int) ([]*types.FileInfo, error) {
	start := time.Now()
	files, err := a.StorageWrapper.List(ctx, prefix, limit)
	duration := time.Since(start)

	fields := logrus.Fields{
		"operation": "list",
		"prefix":    prefix,
		"limit":     limit,
		"duration":  duration,
	}

	if err != nil {
		fields["error"] = err.Error()
		a.logger.WithFields(fields).Error("List failed")
	} else {
		fields["count"] = len(files)
		a.logger.WithFields(fields).Info("List completed")
	}

	return files, err
}

// GeneratePresignedURL logs presigned URL generation
func (a *auditStorage) GeneratePresignedURL(ctx context.Context, key string, expiry time.Duration, operation types.Operation) (string, error) {
	start := time.Now()
	url, err := a.StorageWrapper.GeneratePresignedURL(ctx, key, expiry, operation)
	duration := time.Since(start)

	fields := logrus.Fields{
		"operation":      "generate_presigned_url",
		"key":            key,
		"expiry":         expiry,
		"url_operation":  operation,
		"duration":       duration,
	}

	if err != nil {
		fields["error"] = err.Error()
		a.logger.WithFields(fields).Error("Generate presigned URL failed")
	} else {
		a.logger.WithFields(fields).Info("Generate presigned URL completed")
	}

	return url, err
}