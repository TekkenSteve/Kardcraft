package middleware

import (
	"context"
	"testing"

	"file-storage/internal/types"
)

type metadataStorage struct {
	types.Storage
	metadata *types.FileMetadata
}

func (s *metadataStorage) GetMetadata(context.Context, string) (*types.FileMetadata, error) {
	return s.metadata, nil
}

func TestCompressionGetMetadataReportsOriginalSize(t *testing.T) {
	storage := &metadataStorage{
		metadata: &types.FileMetadata{
			ContentLength: 62,
			CustomMeta: map[string]string{
				"compression":   "gzip",
				"original_size": "38",
			},
		},
	}
	wrapped := NewCompressionMiddleware("gzip").Wrap(storage)

	metadata, err := wrapped.GetMetadata(context.Background(), "probe.txt")
	if err != nil {
		t.Fatal(err)
	}
	if metadata.ContentLength != 38 {
		t.Fatalf("expected original size 38, got %d", metadata.ContentLength)
	}
}
