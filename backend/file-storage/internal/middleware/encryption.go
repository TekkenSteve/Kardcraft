package middleware

import (
	"bytes"
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"fmt"
	"io"

	"file-storage/internal/types"
)

// EncryptionMiddleware provides encryption for storage operations
type EncryptionMiddleware struct {
	key []byte
}

// NewEncryptionMiddleware creates a new encryption middleware
func NewEncryptionMiddleware(key string) (*EncryptionMiddleware, error) {
	if len(key) != 32 {
		return nil, fmt.Errorf("encryption key must be 32 bytes long")
	}
	
	return &EncryptionMiddleware{
		key: []byte(key),
	}, nil
}

// Wrap wraps a storage instance with encryption
func (e *EncryptionMiddleware) Wrap(s types.Storage) types.Storage {
	return &encryptionStorage{
		StorageWrapper: NewStorageWrapper(s),
		key:            e.key,
	}
}

type encryptionStorage struct {
	*StorageWrapper
	key []byte
}

// Upload encrypts data before uploading
func (e *encryptionStorage) Upload(ctx context.Context, key string, reader io.Reader, metadata *types.FileMetadata) error {
	// Read all data
	data, err := io.ReadAll(reader)
	if err != nil {
		return &types.StorageError{
			Op:   "upload",
			Key:  key,
			Err:  err,
			Code: types.ErrorCodeInternal,
		}
	}

	// Encrypt the data
	encryptedData, err := e.encrypt(data)
	if err != nil {
		return &types.StorageError{
			Op:   "upload",
			Key:  key,
			Err:  err,
			Code: types.ErrorCodeInternal,
		}
	}

	// Update metadata to indicate encryption
	if metadata == nil {
		metadata = &types.FileMetadata{
			CustomMeta: make(map[string]string),
		}
	}
	if metadata.CustomMeta == nil {
		metadata.CustomMeta = make(map[string]string)
	}
	
	metadata.CustomMeta["encrypted"] = "true"
	metadata.CustomMeta["original_size"] = fmt.Sprintf("%d", len(data))
	metadata.ContentLength = int64(len(encryptedData))

	return e.StorageWrapper.Upload(ctx, key, bytes.NewReader(encryptedData), metadata)
}

// Download decrypts data after downloading
func (e *encryptionStorage) Download(ctx context.Context, key string) (io.ReadCloser, *types.FileMetadata, error) {
	reader, metadata, err := e.StorageWrapper.Download(ctx, key)
	if err != nil {
		return nil, nil, err
	}

	// Check if file is encrypted
	if metadata == nil || metadata.CustomMeta == nil {
		return reader, metadata, nil
	}

	encrypted, exists := metadata.CustomMeta["encrypted"]
	if !exists || encrypted != "true" {
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

	// Decrypt the data
	decryptedData, err := e.decrypt(data)
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

	return io.NopCloser(bytes.NewReader(decryptedData)), metadata, nil
}

// encrypt encrypts data using AES-GCM
func (e *encryptionStorage) encrypt(data []byte) ([]byte, error) {
	block, err := aes.NewCipher(e.key)
	if err != nil {
		return nil, err
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}

	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, err
	}

	ciphertext := gcm.Seal(nonce, nonce, data, nil)
	return ciphertext, nil
}

// decrypt decrypts data using AES-GCM
func (e *encryptionStorage) decrypt(data []byte) ([]byte, error) {
	block, err := aes.NewCipher(e.key)
	if err != nil {
		return nil, err
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}

	nonceSize := gcm.NonceSize()
	if len(data) < nonceSize {
		return nil, fmt.Errorf("ciphertext too short")
	}

	nonce, ciphertext := data[:nonceSize], data[nonceSize:]
	plaintext, err := gcm.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return nil, err
	}

	return plaintext, nil
}