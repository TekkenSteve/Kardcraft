package middleware

import (
	"context"
	"io"
	"time"

	"file-storage/internal/types"
)

// Middleware defines the interface for storage middleware
type Middleware interface {
	// Wrap wraps a storage instance with middleware functionality
	Wrap(types.Storage) types.Storage
}

// Chain represents a chain of middleware
type Chain struct {
	middlewares []Middleware
}

// NewChain creates a new middleware chain
func NewChain(middlewares ...Middleware) *Chain {
	return &Chain{
		middlewares: middlewares,
	}
}

// Apply applies the middleware chain to a storage instance
func (c *Chain) Apply(s types.Storage) types.Storage {
	// Apply middleware in reverse order so the first middleware
	// in the chain is the outermost wrapper
	for i := len(c.middlewares) - 1; i >= 0; i-- {
		s = c.middlewares[i].Wrap(s)
	}
	return s
}

// Add adds a middleware to the chain
func (c *Chain) Add(middleware Middleware) {
	c.middlewares = append(c.middlewares, middleware)
}

// MiddlewareFunc is a function type that implements Middleware
type MiddlewareFunc func(types.Storage) types.Storage

// Wrap implements the Middleware interface
func (f MiddlewareFunc) Wrap(s types.Storage) types.Storage {
	return f(s)
}

// StorageWrapper is a base wrapper that implements the Storage interface
// by delegating all calls to the wrapped storage
type StorageWrapper struct {
	types.Storage
}

// NewStorageWrapper creates a new storage wrapper
func NewStorageWrapper(s types.Storage) *StorageWrapper {
	return &StorageWrapper{Storage: s}
}

// Upload delegates to the wrapped storage
func (w *StorageWrapper) Upload(ctx context.Context, key string, reader io.Reader, metadata *types.FileMetadata) error {
	return w.Storage.Upload(ctx, key, reader, metadata)
}

// Download delegates to the wrapped storage
func (w *StorageWrapper) Download(ctx context.Context, key string) (io.ReadCloser, *types.FileMetadata, error) {
	return w.Storage.Download(ctx, key)
}

// Delete delegates to the wrapped storage
func (w *StorageWrapper) Delete(ctx context.Context, key string) error {
	return w.Storage.Delete(ctx, key)
}

// Exists delegates to the wrapped storage
func (w *StorageWrapper) Exists(ctx context.Context, key string) (bool, error) {
	return w.Storage.Exists(ctx, key)
}

// List delegates to the wrapped storage
func (w *StorageWrapper) List(ctx context.Context, prefix string, limit int) ([]*types.FileInfo, error) {
	return w.Storage.List(ctx, prefix, limit)
}

// GetMetadata delegates to the wrapped storage
func (w *StorageWrapper) GetMetadata(ctx context.Context, key string) (*types.FileMetadata, error) {
	return w.Storage.GetMetadata(ctx, key)
}

// UpdateMetadata delegates to the wrapped storage
func (w *StorageWrapper) UpdateMetadata(ctx context.Context, key string, metadata *types.FileMetadata) error {
	return w.Storage.UpdateMetadata(ctx, key, metadata)
}

// GeneratePresignedURL delegates to the wrapped storage
func (w *StorageWrapper) GeneratePresignedURL(ctx context.Context, key string, expiry time.Duration, operation types.Operation) (string, error) {
	return w.Storage.GeneratePresignedURL(ctx, key, expiry, operation)
}

// Close delegates to the wrapped storage
func (w *StorageWrapper) Close() error {
	return w.Storage.Close()
}