package dto

type SessionControlHTTPBody struct {
	Reason string `json:"reason"`
}

type InitUploadHTTPBody struct {
	FileName   string `json:"filename"`
	ChunkCount int    `json:"chunk_count"`
	SessionID  string `json:"session_id"`
}
