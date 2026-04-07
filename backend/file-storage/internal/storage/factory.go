package storage

import (
	"context"
	"fmt"

	"file-storage/internal/config"
	"file-storage/internal/storage/providers"
)

// Factory creates storage instances
type Factory struct {
	config *config.Config
}

// NewFactory creates a new storage factory
func NewFactory(cfg *config.Config) *Factory {
	return &Factory{
		config: cfg,
	}
}

// CreateStorage creates a storage instance for the specified provider
func (f *Factory) CreateStorage(ctx context.Context, providerName string) (Storage, error) {
	if providerName == "" {
		providerName = f.config.Storage.DefaultProvider
	}
	
	providerConfig, exists := f.config.Storage.Providers[providerName]
	if !exists {
		return nil, fmt.Errorf("provider %s not configured", providerName)
	}
	
	switch providerName {
	case "minio":
		return providers.NewMinIOStorage(ctx, providerConfig)
	case "s3":
		return providers.NewS3Storage(ctx, providerConfig)
	case "gcs":
		return providers.NewGCSStorage(ctx, providerConfig)
	case "azure":
		return providers.NewAzureStorage(ctx, providerConfig)
	case "file":
		return providers.NewFileStorage(ctx, providerConfig)
	case "memory":
		return providers.NewMemoryStorage(ctx, providerConfig)
	default:
		return nil, fmt.Errorf("unsupported provider: %s", providerName)
	}
}

// CreateDefaultStorage creates the default storage instance
func (f *Factory) CreateDefaultStorage(ctx context.Context) (Storage, error) {
	return f.CreateStorage(ctx, f.config.Storage.DefaultProvider)
}

// ListProviders returns the list of configured providers
func (f *Factory) ListProviders() []string {
	providers := make([]string, 0, len(f.config.Storage.Providers))
	for name := range f.config.Storage.Providers {
		providers = append(providers, name)
	}
	return providers
}

// Get returns a storage instance for the specified provider (cached or new)
func (f *Factory) Get(providerName string) (Storage, error) {
	return f.CreateStorage(context.Background(), providerName)
}