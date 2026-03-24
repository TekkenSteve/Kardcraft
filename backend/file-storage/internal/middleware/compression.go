package middleware

import (
	"bytes"
	"compress/gzip"
	"context"
	"fmt"
	"io"
	"strings"

	"file-storage/internal/types"
)

// CompressionMiddleware provides compression for storage operations
type CompressionMiddleware struct {
	algorithm string
}

// NewCompressionMiddleware creates a new compression middleware
func NewCompressionMiddleware(algorithm string) *CompressionMiddleware {
	return &CompressionMiddleware{
		algorithm: algorithm,
	}
}

// Wrap wraps a storage instance with compression
func (c *CompressionMiddleware) Wrap(s types.Storage) types.Storage {
	return &compressionStorage{
		StorageWrapper: NewStorageWrapper(s),
		algorithm:      c.algorithm,
	}
}

type compressionStorage struct {
	*StorageWrapper
	algorithm string
}

// Upload compresses data before uploading
func (c *compressionStorage) Upload(ctx context.Context, key string, reader io.Reader, metadata *types.FileMetadata) error {
	// Check if file should be compressed based on content type
	if metadata != nil && !c.shouldCompress(metadata.ContentType) {
		return c.StorageWrapper.Upload(ctx, key, reader, metadata)
	}

	// Compress the data
	compressedData, err := c.compress(reader)
	if err != nil {
		return &types.StorageError{
			Op:   "upload",
			Key:  key,
			Err:  err,
			Code: types.ErrorCodeInternal,
		}
	}

	// Update metadata to indicate compression
	if metadata == nil {
		metadata = &types.FileMetadata{
			CustomMeta: make(map[string]string),
		}
	}
	if metadata.CustomMeta == nil {
		metadata.CustomMeta = make(map[string]string)
	}
	
	metadata.CustomMeta["compression"] = c.algorithm
	metadata.CustomMeta["original_size"] = fmt.Sprintf("%d", metadata.ContentLength)
	metadata.ContentLength = int64(len(compressedData))

	return c.StorageWrapper.Upload(ctx, key, bytes.NewReader(compressedData), metadata)
}

// Download decompresses data after downloading
func (c *compressionStorage) Download(ctx context.Context, key string) (io.ReadCloser, *types.FileMetadata, error) {
	reader, metadata, err := c.StorageWrapper.Download(ctx, key)
	if err != nil {
		return nil, nil, err
	}

	// Check if file is compressed
	if metadata == nil || metadata.CustomMeta == nil {
		return reader, metadata, nil
	}

	compression, exists := metadata.CustomMeta["compression"]
	if !exists || compression != c.algorithm {
		return reader, metadata, nil
	}

	// Read all data
	data, err := io.ReadAll(reader)
	reader.Close()
	if err != nil {
		return nil, nil, &types.StorageError{
			Op:   "download",
			Key:  key,
			Err:  err,
			Code: types.ErrorCodeInternal,
		}
	}

	// Decompress the data
	decompressedData, err := c.decompress(data)
	if err != nil {
		return nil, nil, &types.StorageError{
			Op:   "download",
			Key:  key,
			Err:  err,
			Code: types.ErrorCodeInternal,
		}
	}

	// Update metadata to reflect original size
	if originalSizeStr, exists := metadata.CustomMeta["original_size"]; exists {
		var originalSize int64
		fmt.Sscanf(originalSizeStr, "%d", &originalSize)
		metadata.ContentLength = originalSize
	}

	return io.NopCloser(bytes.NewReader(decompressedData)), metadata, nil
}

// compress compresses data using the specified algorithm
func (c *compressionStorage) compress(reader io.Reader) ([]byte, error) {
	switch c.algorithm {
	case "gzip":
		return c.compressGzip(reader)
	default:
		return nil, fmt.Errorf("unsupported compression algorithm: %s", c.algorithm)
	}
}

// decompress decompresses data using the specified algorithm
func (c *compressionStorage) decompress(data []byte) ([]byte, error) {
	switch c.algorithm {
	case "gzip":
		return c.decompressGzip(data)
	default:
		return nil, fmt.Errorf("unsupported compression algorithm: %s", c.algorithm)
	}
}

// compressGzip compresses data using gzip
func (c *compressionStorage) compressGzip(reader io.Reader) ([]byte, error) {
	var buf bytes.Buffer
	writer := gzip.NewWriter(&buf)
	
	_, err := io.Copy(writer, reader)
	if err != nil {
		return nil, err
	}
	
	err = writer.Close()
	if err != nil {
		return nil, err
	}
	
	return buf.Bytes(), nil
}

// decompressGzip decompresses gzip data
func (c *compressionStorage) decompressGzip(data []byte) ([]byte, error) {
	reader, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	defer reader.Close()
	
	return io.ReadAll(reader)
}

// shouldCompress determines if a file should be compressed based on content type
func (c *compressionStorage) shouldCompress(contentType string) bool {
	// Don't compress already compressed formats
	compressedTypes := []string{
		"image/jpeg",
		"image/png",
		"image/gif",
		"video/",
		"audio/",
		"application/zip",
		"application/gzip",
		"application/x-gzip",
		"application/x-compress",
		"application/x-compressed",
	}
	
	contentType = strings.ToLower(contentType)
	for _, compressedType := range compressedTypes {
		if strings.HasPrefix(contentType, compressedType) {
			return false
		}
	}
	
	return true
}