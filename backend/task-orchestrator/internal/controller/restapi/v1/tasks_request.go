package v1

import (
	"fmt"
	"strings"
	"time"
)

func resolveSessionID(raw string) string {
	sessionID := strings.TrimSpace(raw)
	if sessionID != "" {
		return sessionID
	}
	return fmt.Sprintf("session_%d", time.Now().UTC().UnixNano())
}

func normalizeInputAttachments(raw []Attachment) []map[string]any {
	if len(raw) == 0 {
		return nil
	}
	out := make([]map[string]any, 0, len(raw))
	for _, item := range raw {
		fileID := strings.TrimSpace(item.FileID)
		filename := strings.TrimSpace(item.Filename)
		if fileID == "" || filename == "" {
			continue
		}
		size := item.Size
		if size < 0 {
			size = 0
		}
		mimeType := strings.TrimSpace(item.MimeType)
		if mimeType == "" {
			mimeType = "application/octet-stream"
		}
		out = append(out, map[string]any{
			"file_id":   fileID,
			"filename":  filename,
			"size":      size,
			"mime_type": mimeType,
		})
	}
	if len(out) == 0 {
		return nil
	}
	return out
}
