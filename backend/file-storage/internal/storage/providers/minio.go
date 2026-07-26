package providers

import (
	"context"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"gocloud.dev/blob"
	"gocloud.dev/blob/s3blob"

	"file-storage/internal/config"
	"file-storage/internal/types"
)

// MinIOStorage implements Storage interface using MinIO (S3 compatible)
type MinIOStorage struct {
	bucket   *blob.Bucket
	s3Client *s3.Client
	config   config.ProviderConfig
}

// NewMinIOStorage creates a new MinIO storage instance
func NewMinIOStorage(ctx context.Context, cfg config.ProviderConfig) (*MinIOStorage, error) {
	endpoint := cfg.Endpoint
	if !strings.HasPrefix(endpoint, "http://") && !strings.HasPrefix(endpoint, "https://") {
		if cfg.Secure {
			endpoint = "https://" + endpoint
		} else {
			endpoint = "http://" + endpoint
		}
	}

	// Setup AWS v2 configuration with MinIO endpoint
	awsCfg, err := awsconfig.LoadDefaultConfig(ctx,
		awsconfig.WithRegion(cfg.Region),
		awsconfig.WithCredentialsProvider(credentials.NewStaticCredentialsProvider(cfg.AccessKey, cfg.SecretKey, "")),
		awsconfig.WithBaseEndpoint(endpoint),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}

	// Create S3 client
	s3Client := s3.NewFromConfig(awsCfg, func(o *s3.Options) {
		o.UsePathStyle = true // Essential for MinIO
	})

	// Open the bucket using s3blob
	bucket, err := s3blob.OpenBucket(ctx, s3Client, cfg.Bucket, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to open MinIO bucket %s: %w", cfg.Bucket, err)
	}

	return &MinIOStorage{
		bucket:   bucket,
		s3Client: s3Client,
		config:   cfg,
	}, nil
}

// Upload uploads a file to MinIO
func (m *MinIOStorage) Upload(ctx context.Context, key string, reader io.Reader, metadata *types.FileMetadata) error {
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

// Download downloads a file from MinIO
func (m *MinIOStorage) Download(ctx context.Context, key string) (io.ReadCloser, *types.FileMetadata, error) {
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

	attrs, err := m.bucket.Attributes(ctx, key)
	if err != nil {
		reader.Close()
		return nil, nil, &types.StorageError{
			Op:   "get_metadata",
			Key:  key,
			Err:  err,
			Code: types.ErrorCodeInternal,
		}
	}

	metadata := &types.FileMetadata{
		ContentType:   attrs.ContentType,
		ContentLength: attrs.Size,
		ETag:          attrs.ETag,
		LastModified:  attrs.ModTime,
		CustomMeta:    cloneMetadata(attrs.Metadata),
	}

	return reader, metadata, nil
}

// Delete deletes a file from MinIO
func (m *MinIOStorage) Delete(ctx context.Context, key string) error {
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

// Exists checks if a file exists in MinIO
func (m *MinIOStorage) Exists(ctx context.Context, key string) (bool, error) {
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

// List lists files in MinIO with optional prefix
func (m *MinIOStorage) List(ctx context.Context, prefix string, limit int) ([]*types.FileInfo, error) {
	opts := &blob.ListOptions{
		Prefix: prefix,
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
			ETag:         "",
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

// GetMetadata gets file metadata from MinIO
func (m *MinIOStorage) GetMetadata(ctx context.Context, key string) (*types.FileMetadata, error) {
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
		ETag:          attrs.ETag,
		LastModified:  attrs.ModTime,
		CustomMeta:    cloneMetadata(attrs.Metadata),
	}, nil
}

func cloneMetadata(source map[string]string) map[string]string {
	cloned := make(map[string]string, len(source))
	for key, value := range source {
		cloned[key] = value
	}
	return cloned
}

// UpdateMetadata updates file metadata in MinIO
func (m *MinIOStorage) UpdateMetadata(ctx context.Context, key string, metadata *types.FileMetadata) error {
	// Note: go-cloud blob doesn't support metadata updates directly
	// This would require provider-specific implementation
	return &types.StorageError{
		Op:      "update_metadata",
		Key:     key,
		Code:    types.ErrorCodeInternal,
		Message: "metadata update not supported by go-cloud blob interface",
	}
}

// GeneratePresignedURL generates a presigned URL for MinIO
func (m *MinIOStorage) GeneratePresignedURL(ctx context.Context, key string, expiry time.Duration, operation types.Operation) (string, error) {
	publicEndpoint := strings.TrimSpace(os.Getenv("MINIO_PUBLIC_ENDPOINT"))
	if publicEndpoint != "" {
		url, err := m.generatePublicPresignedURL(ctx, key, expiry, operation, publicEndpoint)
		if err == nil {
			return url, nil
		}
	}

	opts := &blob.SignedURLOptions{
		Expiry: expiry,
	}

	switch operation {
	case types.OperationRead:
		opts.Method = "GET"
	case types.OperationWrite:
		opts.Method = "PUT"
	case types.OperationDelete:
		opts.Method = "DELETE"
	default:
		return "", &types.StorageError{
			Op:      "generate_presigned_url",
			Key:     key,
			Code:    types.ErrorCodeInvalidArgument,
			Message: fmt.Sprintf("unsupported operation: %s", operation),
		}
	}

	url, err := m.bucket.SignedURL(ctx, key, opts)
	if err != nil {
		return "", &types.StorageError{
			Op:   "generate_presigned_url",
			Key:  key,
			Err:  err,
			Code: types.ErrorCodeInternal,
		}
	}

	return url, nil
}

func (m *MinIOStorage) generatePublicPresignedURL(
	ctx context.Context,
	key string,
	expiry time.Duration,
	operation types.Operation,
	publicEndpoint string,
) (string, error) {
	if !strings.HasPrefix(publicEndpoint, "http://") && !strings.HasPrefix(publicEndpoint, "https://") {
		if m.config.Secure {
			publicEndpoint = "https://" + publicEndpoint
		} else {
			publicEndpoint = "http://" + publicEndpoint
		}
	}

	awsCfg, err := awsconfig.LoadDefaultConfig(ctx,
		awsconfig.WithRegion(m.config.Region),
		awsconfig.WithCredentialsProvider(credentials.NewStaticCredentialsProvider(m.config.AccessKey, m.config.SecretKey, "")),
		awsconfig.WithBaseEndpoint(publicEndpoint),
	)
	if err != nil {
		return "", err
	}

	publicS3Client := s3.NewFromConfig(awsCfg, func(o *s3.Options) {
		o.UsePathStyle = true
	})
	presignClient := s3.NewPresignClient(publicS3Client)

	switch operation {
	case types.OperationRead:
		resp, err := presignClient.PresignGetObject(ctx, &s3.GetObjectInput{
			Bucket: &m.config.Bucket,
			Key:    &key,
		}, s3.WithPresignExpires(expiry))
		if err != nil {
			return "", err
		}
		return resp.URL, nil
	case types.OperationWrite:
		resp, err := presignClient.PresignPutObject(ctx, &s3.PutObjectInput{
			Bucket: &m.config.Bucket,
			Key:    &key,
		}, s3.WithPresignExpires(expiry))
		if err != nil {
			return "", err
		}
		return resp.URL, nil
	case types.OperationDelete:
		resp, err := presignClient.PresignDeleteObject(ctx, &s3.DeleteObjectInput{
			Bucket: &m.config.Bucket,
			Key:    &key,
		}, s3.WithPresignExpires(expiry))
		if err != nil {
			return "", err
		}
		return resp.URL, nil
	default:
		return "", &types.StorageError{
			Op:      "generate_presigned_url",
			Key:     key,
			Code:    types.ErrorCodeInvalidArgument,
			Message: fmt.Sprintf("unsupported operation: %s", operation),
		}
	}
}

// Close closes the MinIO storage connection
func (m *MinIOStorage) Close() error {
	return m.bucket.Close()
}
