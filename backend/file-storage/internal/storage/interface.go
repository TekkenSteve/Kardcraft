package storage

import (
	"file-storage/internal/types"
)

// Re-export types for backward compatibility
type Storage = types.Storage
type FileMetadata = types.FileMetadata
type FileInfo = types.FileInfo
type Operation = types.Operation
type StorageError = types.StorageError
type ErrorCode = types.ErrorCode

// Re-export constants
const (
	OperationRead   = types.OperationRead
	OperationWrite  = types.OperationWrite
	OperationDelete = types.OperationDelete
	
	ErrorCodeNotFound          = types.ErrorCodeNotFound
	ErrorCodeAlreadyExists     = types.ErrorCodeAlreadyExists
	ErrorCodePermissionDenied  = types.ErrorCodePermissionDenied
	ErrorCodeInvalidArgument   = types.ErrorCodeInvalidArgument
	ErrorCodeInternal          = types.ErrorCodeInternal
	ErrorCodeUnavailable       = types.ErrorCodeUnavailable
	ErrorCodeQuotaExceeded     = types.ErrorCodeQuotaExceeded
)