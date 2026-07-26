package config

import (
	"fmt"
	"os"
	"time"

	"gopkg.in/yaml.v3"
)

// Config represents the application configuration
type Config struct {
	Server     ServerConfig     `yaml:"server"`
	Storage    StorageConfig    `yaml:"storage"`
	Middleware MiddlewareConfig `yaml:"middleware"`
	Policies   PoliciesConfig   `yaml:"policies"`
	Logging    LoggingConfig    `yaml:"logging"`
}

// ServerConfig contains server configuration
type ServerConfig struct {
	Port string `yaml:"port"`
	Host string `yaml:"host"`
}

// StorageConfig contains storage configuration
type StorageConfig struct {
	DefaultProvider string                    `yaml:"default_provider"`
	Providers       map[string]ProviderConfig `yaml:"providers"`
}

// ProviderConfig contains provider-specific configuration
type ProviderConfig struct {
	// MinIO/S3 configuration
	Endpoint  string `yaml:"endpoint"`
	AccessKey string `yaml:"access_key"`
	SecretKey string `yaml:"secret_key"`
	Secure    bool   `yaml:"secure"`
	Bucket    string `yaml:"bucket"`
	Region    string `yaml:"region"`

	// Azure configuration
	AccountName string `yaml:"account_name"`
	Container   string `yaml:"container"`

	// File system configuration
	BasePath string `yaml:"base_path"`

	// GCS configuration
	CredentialsFile string `yaml:"credentials_file"`

	// Memory configuration
	Enabled bool `yaml:"enabled"`
}

// MiddlewareConfig contains middleware configuration
type MiddlewareConfig struct {
	Encryption  EncryptionConfig  `yaml:"encryption"`
	Compression CompressionConfig `yaml:"compression"`
	Cache       CacheConfig       `yaml:"cache"`
	Audit       AuditConfig       `yaml:"audit"`
}

// EncryptionConfig contains encryption configuration
type EncryptionConfig struct {
	Enabled bool   `yaml:"enabled"`
	Key     string `yaml:"key"`
}

// CompressionConfig contains compression configuration
type CompressionConfig struct {
	Enabled   bool   `yaml:"enabled"`
	Algorithm string `yaml:"algorithm"`
}

// CacheConfig contains cache configuration
type CacheConfig struct {
	Enabled bool          `yaml:"enabled"`
	TTL     time.Duration `yaml:"ttl"`
	MaxSize string        `yaml:"max_size"`
}

// AuditConfig contains audit configuration
type AuditConfig struct {
	Enabled  bool   `yaml:"enabled"`
	LogLevel string `yaml:"log_level"`
}

// PoliciesConfig contains file policies
type PoliciesConfig struct {
	MaxFileSize       string   `yaml:"max_file_size"`
	AllowedExtensions []string `yaml:"allowed_extensions"`
	ScanForMalware    bool     `yaml:"scan_for_malware"`
}

// LoggingConfig contains logging configuration
type LoggingConfig struct {
	Level  string `yaml:"level"`
	Format string `yaml:"format"`
}

// LoadConfig loads configuration from file and environment variables
func LoadConfig(configPath string) (*Config, error) {
	config := &Config{}

	// Load from file
	if configPath != "" {
		data, err := os.ReadFile(configPath)
		if err != nil {
			return nil, fmt.Errorf("failed to read config file: %w", err)
		}

		if err := yaml.Unmarshal(data, config); err != nil {
			return nil, fmt.Errorf("failed to unmarshal config: %w", err)
		}
	}

	// Override with environment variables
	config.overrideWithEnv()

	return config, nil
}

// overrideWithEnv overrides configuration with environment variables
func (c *Config) overrideWithEnv() {
	if port := os.Getenv("PORT"); port != "" {
		c.Server.Port = port
	}

	if host := os.Getenv("HOST"); host != "" {
		c.Server.Host = host
	}

	if provider := os.Getenv("STORAGE_PROVIDER"); provider != "" {
		c.Storage.DefaultProvider = provider
	}

	// MinIO environment variables
	if endpoint := os.Getenv("MINIO_ENDPOINT"); endpoint != "" {
		if c.Storage.Providers == nil {
			c.Storage.Providers = make(map[string]ProviderConfig)
		}
		minioConfig := c.Storage.Providers["minio"]
		minioConfig.Endpoint = endpoint
		c.Storage.Providers["minio"] = minioConfig
	}

	if accessKey := os.Getenv("MINIO_ACCESS_KEY"); accessKey != "" {
		minioConfig := c.Storage.Providers["minio"]
		minioConfig.AccessKey = accessKey
		c.Storage.Providers["minio"] = minioConfig
	}

	if secretKey := os.Getenv("MINIO_SECRET_KEY"); secretKey != "" {
		minioConfig := c.Storage.Providers["minio"]
		minioConfig.SecretKey = secretKey
		c.Storage.Providers["minio"] = minioConfig
	}

	if bucket := os.Getenv("MINIO_BUCKET"); bucket != "" {
		minioConfig := c.Storage.Providers["minio"]
		minioConfig.Bucket = bucket
		c.Storage.Providers["minio"] = minioConfig
	}
}

// GetAddress returns the server address
func (c *Config) GetAddress() string {
	return c.Server.Host + ":" + c.Server.Port
}
