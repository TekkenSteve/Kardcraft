package providers

import (
	"context"
	"io"
	"time"

	"gocloud.dev/blob"
	"gocloud.dev/blob/memblob"

	"file-storage/internal/config"
	"file-storage/internal/types"
)

// MemoryStorage implements Storage interface using in-memory storage
type MemoryStorage struct {
	bucket *blob.Bucket
	config config.ProviderConfig
}

// NewMemoryStorage creates a new memory storage instance
func NewMemoryStorage(ctx context.Context, cfg config.ProviderConfig) (*MemoryStorage, error) {
	// Create in-memory bucket
	bucket := memblob.OpenBucket(nil)

	return &MemoryStorage{
		bucket: bucket,
		config: cfg,
	}, nil
}

// Upload uploads a file to memory
func (m *MemoryStorage) Upload(ctx context.Context, key string, reader io.Reader, metadata *types.FileMetadata) error {
	opts := &blob.WriterOptions{}
	
	if metadata != nil {
		opts.ContentType = metadata.ContentType
		if metadata.CustomMeta != nil {
			opts.Metadata = metadata.CustomMeta
		}
	}

	writer, err := m.bucket.NewWriter(ctx, key, opts)
	if err != nil {
		return &types.StorageError{
			Op:   "upload",
			Key:  key,
			Err:  err,
			Code: types.ErrorCodeInternal,
		}
	}
	defer writer.Close()

	_, err = io.Copy(writer, reader)
	if err != nil {
		return &types.StorageError{
			Op:   "upload",
			Key:  key,
			Err:  err,
			Code: types.ErrorCodeInternal,
		}
	}

	return nil
}

// Download downloads a file from memory
func (m *MemoryStorage) Download(ctx context.Context, key string) (io.ReadCloser, *types.FileMetadata, error) {
	reader, err := m.bucket.NewReader(ctx, key, nil)
	if err != nil {
		code := types.ErrorCodeInternal
		if err.Error() == "blob (key \""+key+"\") not found" {
			code = types.ErrorCodeNotFound
		}
		return nil, nil, &types.StorageError{
			Op:   "download",
			Key:  key,
			Err:  err,
			Code: code,
		}
	}

	metadata := &types.FileMetadata{
		ContentType:   reader.ContentType(),
		ContentLength: reader.Size(),
		LastModified:  reader.ModTime(),
		CustomMeta:    make(map[string]string),
	}

	return reader, metadata, nil
}

// Delete deletes a file from memory
func (m *MemoryStorage) Delete(ctx context.Context, key string) error {
	err := m.bucket.Delete(ctx, key)
	if err != nil {
		code := types.ErrorCodeInternal
		if err.Error() == "blob (key \""+key+"\") not found" {
			code = types.ErrorCodeNotFound
		}
		return &types.StorageError{
			Op:   "delete",
			Key:  key,
			Err:  err,
			Code: code,
		}
	}
	return nil
}

// Exists checks if a file exists in memory
func (m *MemoryStorage) Exists(ctx context.Context, key string) (bool, error) {
	exists, err := m.bucket.Exists(ctx, key)
	if err != nil {
		return false, &types.StorageError{
			Op:   "exists",
			Key:  key,
			Err:  err,
			Code: types.ErrorCodeInternal,
		}
	}
	return exists, nil
}

// List lists files in memory with optional prefix
func (m *MemoryStorage) List(ctx context.Context, prefix string, limit int) ([]*types.FileInfo, error) {
	opts := &blob.ListOptions{
		Prefix: prefix,
	}
	
	if limit > 0 {
		
	}

	iter := m.bucket.List(opts)
	var files []*types.FileInfo
	
	for {
		obj, err := iter.Next(ctx)
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, &types.StorageError{
				Op:   "list",
				Key:  prefix,
				Err:  err,
				Code: types.ErrorCodeInternal,
			}
		}

		files = append(files, &types.FileInfo{
			Key:          obj.Key,
			Size:         obj.Size,
			LastModified: obj.ModTime,
			ContentType:  "",
			Metadata: &types.FileMetadata{
				ContentType:   "",
				ContentLength: obj.Size,
				LastModified:  obj.ModTime,
				CustomMeta:    make(map[string]string),
			},
		})

		if limit > 0 && len(files) >= limit {
			break
		}
	}

	return files, nil
}

// GetMetadata gets file metadata from memory
func (m *MemoryStorage) GetMetadata(ctx context.Context, key string) (*types.FileMetadata, error) {
	attrs, err := m.bucket.Attributes(ctx, key)
	if err != nil {
		code := types.ErrorCodeInternal
		if err.Error() == "blob (key \""+key+"\") not found" {
			code = types.ErrorCodeNotFound
		}
		return nil, &types.StorageError{
			Op:   "get_metadata",
			Key:  key,
			Err:  err,
			Code: code,
		}
	}

	return &types.FileMetadata{
		ContentType:   attrs.ContentType,
		ContentLength: attrs.Size,
		LastModified:  attrs.ModTime,
		CustomMeta:    make(map[string]string),
	}, nil
}

// UpdateMetadata updates file metadata in memory
func (m *MemoryStorage) UpdateMetadata(ctx context.Context, key string, metadata *types.FileMetadata) error {
	return &types.StorageError{
		Op:      "update_metadata",
		Key:     key,
		Code:    types.ErrorCodeInternal,
		Message: "metadata update not supported by go-cloud blob interface",
	}
}

// GeneratePresignedURL generates a presigned URL for memory storage
func (m *MemoryStorage) GeneratePresignedURL(ctx context.Context, key string, expiry time.Duration, operation types.Operation) (string, error) {
	// Memory storage doesn't support presigned URLs
	return "", &types.StorageError{
		Op:      "generate_presigned_url",
		Key:     key,
		Code:    types.ErrorCodeInternal,
		Message: "presigned URLs not supported by memory storage",
	}
}

// Close closes the memory storage connection
func (m *MemoryStorage) Close() error {
	return m.bucket.Close()
}