package middleware

import (
	"bytes"
	"context"
	"sync"
	"time"
	"io"

	"file-storage/internal/types"
)

// CacheMiddleware provides caching for storage operations
type CacheMiddleware struct {
	cache   *memoryCache
	ttl     time.Duration
	maxSize int64
}

// NewCacheMiddleware creates a new cache middleware
func NewCacheMiddleware(ttl time.Duration, maxSize int64) *CacheMiddleware {
	return &CacheMiddleware{
		cache:   newMemoryCache(),
		ttl:     ttl,
		maxSize: maxSize,
	}
}

// Wrap wraps a storage instance with caching
func (c *CacheMiddleware) Wrap(s types.Storage) types.Storage {
	return &cacheStorage{
		StorageWrapper: NewStorageWrapper(s),
		cache:          c.cache,
		ttl:            c.ttl,
		maxSize:        c.maxSize,
	}
}

type cacheStorage struct {
	*StorageWrapper
	cache   *memoryCache
	ttl     time.Duration
	maxSize int64
}

// Download caches downloaded files
func (c *cacheStorage) Download(ctx context.Context, key string) (io.ReadCloser, *types.FileMetadata, error) {
	// Check cache first
	if entry, exists := c.cache.Get(key); exists && !entry.IsExpired() {
		return io.NopCloser(bytes.NewReader(entry.Data)), entry.Metadata, nil
	}

	// Download from storage
	reader, metadata, err := c.StorageWrapper.Download(ctx, key)
	if err != nil {
		return nil, nil, err
	}

	// Read all data for caching
	data, err := io.ReadAll(reader)
	reader.Close()
	if err != nil {
		return nil, nil, err
	}

	// Cache the data if it's not too large
	if int64(len(data)) <= c.maxSize {
		entry := &cacheEntry{
			Data:      data,
			Metadata:  metadata,
			ExpiresAt: time.Now().Add(c.ttl),
		}
		c.cache.Set(key, entry)
	}

	return io.NopCloser(bytes.NewReader(data)), metadata, nil
}

// Upload invalidates cache on upload
func (c *cacheStorage) Upload(ctx context.Context, key string, reader io.Reader, metadata *types.FileMetadata) error {
	// Invalidate cache
	c.cache.Delete(key)
	
	return c.StorageWrapper.Upload(ctx, key, reader, metadata)
}

// Delete invalidates cache on delete
func (c *cacheStorage) Delete(ctx context.Context, key string) error {
	// Invalidate cache
	c.cache.Delete(key)
	
	return c.StorageWrapper.Delete(ctx, key)
}

// cacheEntry represents a cached file
type cacheEntry struct {
	Data      []byte
	Metadata  *types.FileMetadata
	ExpiresAt time.Time
}

// IsExpired checks if the cache entry is expired
func (e *cacheEntry) IsExpired() bool {
	return time.Now().After(e.ExpiresAt)
}

// memoryCache is a simple in-memory cache
type memoryCache struct {
	mu    sync.RWMutex
	items map[string]*cacheEntry
}

// newMemoryCache creates a new memory cache
func newMemoryCache() *memoryCache {
	cache := &memoryCache{
		items: make(map[string]*cacheEntry),
	}
	
	// Start cleanup goroutine
	go cache.cleanup()
	
	return cache
}

// Get retrieves an item from the cache
func (c *memoryCache) Get(key string) (*cacheEntry, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	
	entry, exists := c.items[key]
	if !exists || entry.IsExpired() {
		return nil, false
	}
	
	return entry, true
}

// Set stores an item in the cache
func (c *memoryCache) Set(key string, entry *cacheEntry) {
	c.mu.Lock()
	defer c.mu.Unlock()
	
	c.items[key] = entry
}

// Delete removes an item from the cache
func (c *memoryCache) Delete(key string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	
	delete(c.items, key)
}

// cleanup removes expired items from the cache
func (c *memoryCache) cleanup() {
	ticker := time.NewTicker(5 * time.Minute)
	defer ticker.Stop()
	
	for range ticker.C {
		c.mu.Lock()
		for key, entry := range c.items {
			if entry.IsExpired() {
				delete(c.items, key)
			}
		}
		c.mu.Unlock()
	}
}