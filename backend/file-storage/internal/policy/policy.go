package policy

import (
	"fmt"
	"path/filepath"
	"strings"

	"file-storage/internal/config"
	"file-storage/internal/types"
)

// PolicyEngine enforces file policies
type PolicyEngine struct {
	config *config.PoliciesConfig
}

// NewPolicyEngine creates a new policy engine
func NewPolicyEngine(cfg *config.PoliciesConfig) *PolicyEngine {
	return &PolicyEngine{
		config: cfg,
	}
}

// ValidateUpload validates a file upload against policies
func (p *PolicyEngine) ValidateUpload(key string, metadata *types.FileMetadata) error {
	// Check file size
	if err := p.validateFileSize(metadata.ContentLength); err != nil {
		return err
	}

	// Check file extension
	if err := p.validateFileExtension(key); err != nil {
		return err
	}

	// Check content type
	if err := p.validateContentType(metadata.ContentType); err != nil {
		return err
	}

	return nil
}

// validateFileSize checks if file size is within limits
func (p *PolicyEngine) validateFileSize(size int64) error {
	if p.config.MaxFileSize == "" {
		return nil
	}

	maxSize, err := parseSize(p.config.MaxFileSize)
	if err != nil {
		return fmt.Errorf("invalid max file size configuration: %w", err)
	}

	if size > maxSize {
		return &types.StorageError{
			Op:      "validate_upload",
			Code:    types.ErrorCodeInvalidArgument,
			Message: fmt.Sprintf("file size %d exceeds maximum allowed size %d", size, maxSize),
		}
	}

	return nil
}

// validateFileExtension checks if file extension is allowed
func (p *PolicyEngine) validateFileExtension(key string) error {
	if len(p.config.AllowedExtensions) == 0 {
		return nil
	}

	ext := strings.ToLower(filepath.Ext(key))
	if ext == "" {
		return &types.StorageError{
			Op:      "validate_upload",
			Code:    types.ErrorCodeInvalidArgument,
			Message: "file must have an extension",
		}
	}

	for _, allowedExt := range p.config.AllowedExtensions {
		if strings.ToLower(allowedExt) == ext {
			return nil
		}
	}

	return &types.StorageError{
		Op:      "validate_upload",
		Code:    types.ErrorCodeInvalidArgument,
		Message: fmt.Sprintf("file extension %s is not allowed", ext),
	}
}

// validateContentType checks if content type is valid
func (p *PolicyEngine) validateContentType(contentType string) error {
	if contentType == "" {
		return &types.StorageError{
			Op:      "validate_upload",
			Code:    types.ErrorCodeInvalidArgument,
			Message: "content type is required",
		}
	}

	// Add more content type validation logic here if needed
	return nil
}

// parseSize parses a size string like "100MB" into bytes
func parseSize(sizeStr string) (int64, error) {
	sizeStr = strings.ToUpper(strings.TrimSpace(sizeStr))
	
	var multiplier int64 = 1
	var numStr string
	
	if strings.HasSuffix(sizeStr, "KB") {
		multiplier = 1024
		numStr = strings.TrimSuffix(sizeStr, "KB")
	} else if strings.HasSuffix(sizeStr, "MB") {
		multiplier = 1024 * 1024
		numStr = strings.TrimSuffix(sizeStr, "MB")
	} else if strings.HasSuffix(sizeStr, "GB") {
		multiplier = 1024 * 1024 * 1024
		numStr = strings.TrimSuffix(sizeStr, "GB")
	} else if strings.HasSuffix(sizeStr, "B") {
		multiplier = 1
		numStr = strings.TrimSuffix(sizeStr, "B")
	} else {
		numStr = sizeStr
	}
	
	var size int64
	if _, err := fmt.Sscanf(numStr, "%d", &size); err != nil {
		return 0, fmt.Errorf("invalid size format: %s", sizeStr)
	}
	
	return size * multiplier, nil
}