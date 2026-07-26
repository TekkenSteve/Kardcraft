package config

import "testing"

func TestOverrideWithEnvSetsMinIOBucket(t *testing.T) {
	t.Setenv("MINIO_BUCKET", "custom-files")

	cfg := &Config{
		Storage: StorageConfig{
			Providers: map[string]ProviderConfig{
				"minio": {Bucket: "default-files"},
			},
		},
	}

	cfg.overrideWithEnv()

	if got := cfg.Storage.Providers["minio"].Bucket; got != "custom-files" {
		t.Fatalf("expected MINIO_BUCKET override, got %q", got)
	}
}
