package types

import (
	"context"
	"io"
	"time"
)

// Storage defines the interface for file storage operations
type Storage interface {
	// Upload uploads a file to storage
	Upload(ctx context.Context, key string, reader io.Reader, metadata *FileMetadata) error
	
	// Download downloads a file from storage
	Download(ctx context.Context, key string) (io.ReadCloser, *FileMetadata, error)
	
	// Delete deletes a file from storage
	Delete(ctx context.Context, key string) error
	
	// Exists checks if a file exists in storage
	Exists(ctx context.Context, key string) (bool, error)
	
	// List lists files in storage with optional prefix
	List(ctx context.Context, prefix string, limit int) ([]*FileInfo, error)
	
	// GetMetadata gets file metadata
	GetMetadata(ctx context.Context, key string) (*FileMetadata, error)
	
	// UpdateMetadata updates file metadata
	UpdateMetadata(ctx context.Context, key string, metadata *FileMetadata) error
	
	// GeneratePresignedURL generates a presigned URL for direct access
	GeneratePresignedURL(ctx context.Context, key string, expiry time.Duration, operation Operation) (string, error)
	
	// Close closes the storage connection
	Close() error
}

// FileMetadata represents file metadata
type FileMetadata struct {
	ContentType   string            `json:"content_type"`
	ContentLength int64             `json:"content_length"`
	ETag          string            `json:"etag"`
	LastModified  time.Time         `json:"last_modified"`
	CustomMeta    map[string]string `json:"custom_meta"`
}

// FileInfo represents file information
type FileInfo struct {
	Key          string        `json:"key"`
	Size         int64         `json:"size"`
	LastModified time.Time     `json:"last_modified"`
	ETag         string        `json:"etag"`
	ContentType  string        `json:"content_type"`
	Metadata     *FileMetadata `json:"metadata"`
}

// Operation represents the type of operation for presigned URLs
type Operation string

const (
	OperationRead   Operation = "read"
	OperationWrite  Operation = "write"
	OperationDelete Operation = "delete"
)

// StorageError represents a storage error
type StorageError struct {
	Op      string
	Key     string
	Err     error
	Code    ErrorCode
	Message string
}

func (e *StorageError) Error() string {
	if e.Message != "" {
		return e.Message
	}
	return e.Err.Error()
}

func (e *StorageError) Unwrap() error {
	return e.Err
}

// ErrorCode represents error codes
type ErrorCode string

const (
	ErrorCodeNotFound          ErrorCode = "NOT_FOUND"
	ErrorCodeAlreadyExists     ErrorCode = "ALREADY_EXISTS"
	ErrorCodePermissionDenied  ErrorCode = "PERMISSION_DENIED"
	ErrorCodeInvalidArgument   ErrorCode = "INVALID_ARGUMENT"
	ErrorCodeInternal          ErrorCode = "INTERNAL"
	ErrorCodeUnavailable       ErrorCode = "UNAVAILABLE"
	ErrorCodeQuotaExceeded     ErrorCode = "QUOTA_EXCEEDED"
)