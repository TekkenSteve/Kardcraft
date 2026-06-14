package v1

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"regexp"
	"sort"
	"strings"
	"task-orchestrator/internal/usecase"
	"time"
)

var templateFieldPattern = regexp.MustCompile(`\{\{([^{}]+)\}\}`)

type ExportsDeps struct {
	WriteJSON  func(w http.ResponseWriter, status int, v any)
	UserID     func(r *http.Request) string
	NowRFC3339 func() string

	HTTPClient     *http.Client
	AnkiRuntimeURL string
	ReadModel      usecase.ReadModel
}

type apkgExportRequest struct {
	SessionID  string `json:"session_id"`
	TemplateID string `json:"template_id,omitempty"`
	DeckName   string `json:"deck_name,omitempty"`
}

type apkgExportRecord struct {
	ExportID       string `json:"export_id"`
	SessionID      string `json:"session_id"`
	UserID         string `json:"user_id"`
	TemplateID     string `json:"template_id"`
	Status         string `json:"status"`
	DeckName       string `json:"deck_name,omitempty"`
	PackageName    string `json:"package_name,omitempty"`
	ConfirmedCount int    `json:"confirmed_count"`
	FileName       string `json:"file_name,omitempty"`
	FileSize       int    `json:"file_size,omitempty"`
	DownloadPath   string `json:"download_path,omitempty"`
	CreatedAt      string `json:"created_at"`
	UpdatedAt      string `json:"updated_at"`
	CompletedAt    string `json:"completed_at,omitempty"`
	Error          string `json:"error,omitempty"`
	APKGBase64     string `json:"-"`
}

func NewApkgExportsHandler(deps ExportsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.ReadModel == nil || !deps.ReadModel.Ready() {
			http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
			return
		}
		switch r.Method {
		case http.MethodPost:
			handleCreateApkgExport(w, r, deps)
		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	}
}

func NewApkgExportDetailRouter(deps ExportsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.ReadModel == nil || !deps.ReadModel.Ready() {
			http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
			return
		}
		trimmed := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/exports/apkg/"), "/")
		if trimmed == "" {
			http.NotFound(w, r)
			return
		}
		parts := strings.Split(trimmed, "/")
		exportID := strings.TrimSpace(parts[0])
		if exportID == "" {
			http.NotFound(w, r)
			return
		}
		if len(parts) == 1 {
			if r.Method != http.MethodGet {
				http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
				return
			}
			handleGetApkgExport(w, r, deps, exportID)
			return
		}
		if len(parts) == 2 && parts[1] == "download" {
			if r.Method != http.MethodGet {
				http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
				return
			}
			handleDownloadApkgExport(w, r, deps, exportID)
			return
		}
		http.NotFound(w, r)
	}
}

func handleCreateApkgExport(w http.ResponseWriter, r *http.Request, deps ExportsDeps) {
	var req apkgExportRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	req.SessionID = strings.TrimSpace(req.SessionID)
	req.TemplateID = strings.TrimSpace(req.TemplateID)
	req.DeckName = strings.TrimSpace(req.DeckName)
	if req.SessionID == "" {
		http.Error(w, "session_id is required", http.StatusBadRequest)
		return
	}

	userID := deps.UserID(r)
	if _, err := deps.ReadModel.GetSession(r.Context(), req.SessionID, userID); err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}

	workspace, err := deps.ReadModel.LoadWorkspace(r.Context(), req.SessionID)
	if err != nil {
		http.Error(w, "failed to load workspace", http.StatusInternalServerError)
		return
	}
	if workspace == nil {
		workspace = map[string]any{
			"session_id": req.SessionID,
			"version":    0,
			"status":     "not_started",
			"card_count": 0,
			"cards":      []map[string]any{},
		}
	}
	exportsMap := ensureApkgExportMap(workspace)
	exportID := fmt.Sprintf("apkg_%d", time.Now().UTC().UnixNano())
	now := deps.NowRFC3339()
	record := apkgExportRecord{
		ExportID:     exportID,
		SessionID:    req.SessionID,
		UserID:       userID,
		TemplateID:   req.TemplateID,
		Status:       "processing",
		DeckName:     req.DeckName,
		DownloadPath: fmt.Sprintf("/api/v1/exports/apkg/%s/download", exportID),
		CreatedAt:    now,
		UpdatedAt:    now,
	}
	exportsMap[exportID] = recordToMap(record)
	workspace["apkg_exports"] = exportsMap
	if err := deps.ReadModel.SaveWorkspace(r.Context(), req.SessionID, workspace); err != nil {
		http.Error(w, "failed to create export task", http.StatusInternalServerError)
		return
	}
	deps.WriteJSON(w, http.StatusAccepted, sanitizeExportRecord(record))

	go runApkgExportTask(deps, record)
}

func handleGetApkgExport(w http.ResponseWriter, r *http.Request, deps ExportsDeps, exportID string) {
	userID := deps.UserID(r)
	sessionID := strings.TrimSpace(r.URL.Query().Get("session_id"))
	if sessionID == "" {
		http.Error(w, "session_id query is required", http.StatusBadRequest)
		return
	}
	if _, err := deps.ReadModel.GetSession(r.Context(), sessionID, userID); err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}
	workspace, err := deps.ReadModel.LoadWorkspace(r.Context(), sessionID)
	if err != nil {
		http.Error(w, "failed to load workspace", http.StatusInternalServerError)
		return
	}
	rec, ok := findExportRecord(workspace, exportID, userID)
	if !ok {
		http.Error(w, "export task not found", http.StatusNotFound)
		return
	}
	deps.WriteJSON(w, http.StatusOK, sanitizeExportRecord(rec))
}

func handleDownloadApkgExport(w http.ResponseWriter, r *http.Request, deps ExportsDeps, exportID string) {
	userID := deps.UserID(r)
	sessionID := strings.TrimSpace(r.URL.Query().Get("session_id"))
	if sessionID == "" {
		http.Error(w, "session_id query is required", http.StatusBadRequest)
		return
	}
	if _, err := deps.ReadModel.GetSession(r.Context(), sessionID, userID); err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}
	workspace, err := deps.ReadModel.LoadWorkspace(r.Context(), sessionID)
	if err != nil {
		http.Error(w, "failed to load workspace", http.StatusInternalServerError)
		return
	}
	rec, ok := findExportRecord(workspace, exportID, userID)
	if !ok {
		http.Error(w, "export task not found", http.StatusNotFound)
		return
	}
	if rec.Status != "completed" || strings.TrimSpace(rec.APKGBase64) == "" {
		http.Error(w, "export task is not ready", http.StatusConflict)
		return
	}
	raw, err := base64.StdEncoding.DecodeString(rec.APKGBase64)
	if err != nil {
		http.Error(w, "invalid package data", http.StatusInternalServerError)
		return
	}
	fileName := strings.TrimSpace(rec.FileName)
	if fileName == "" {
		fileName = "kardcraft_export.apkg"
	}
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=\"%s\"", fileName))
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(raw)
}

func runApkgExportTask(deps ExportsDeps, record apkgExportRecord) {
	ctx := context.Background()
	fail := func(msg string) {
		updateExportRecord(ctx, deps, record.SessionID, record.ExportID, func(cur apkgExportRecord) apkgExportRecord {
			cur.Status = "failed"
			cur.Error = msg
			cur.UpdatedAt = deps.NowRFC3339()
			return cur
		})
	}

	workspace, err := deps.ReadModel.LoadWorkspace(ctx, record.SessionID)
	if err != nil {
		fail("failed to load workspace")
		return
	}
	normalizedWorkspace := NormalizeWorkspaceResponse(workspace, record.SessionID)
	cards := extractWorkspaceCards(normalizedWorkspace)
	confirmed := filterConfirmedCards(cards)
	if len(confirmed) == 0 {
		fail("no confirmed cards to export")
		return
	}
	record.ConfirmedCount = len(confirmed)
	templateID, err := resolveExportTemplateID(record.TemplateID, normalizedWorkspace, func() (string, error) {
		resolved, err := deps.ReadModel.GetResolvedDefaultTemplate(ctx, record.UserID)
		if err != nil || resolved == nil {
			return "", err
		}
		return strings.TrimSpace(resolved.DefaultTemplateID), nil
	})
	if err != nil {
		fail("no default template configured")
		return
	}
	record.TemplateID = templateID
	templateRow, err := deps.ReadModel.GetAccessibleTemplate(ctx, record.UserID, record.TemplateID)
	if err != nil {
		fail("template not found or inaccessible")
		return
	}
	fieldNames := inferTemplateFieldNames(templateRow.FrontHTML, templateRow.BackHTML)
	if len(fieldNames) == 0 {
		fieldNames = []string{"Front", "Back"}
	}
	if strings.TrimSpace(record.DeckName) == "" {
		record.DeckName = fmt.Sprintf("Kardcraft::%s", record.SessionID)
	}
	record.PackageName = fmt.Sprintf("kardcraft_%s_%d", sanitizeFileName(record.SessionID), time.Now().UTC().Unix())

	packageCards := make([]map[string]any, 0, len(confirmed))
	for _, c := range confirmed {
		fields, tags := buildCardFields(c, fieldNames, record.DeckName)
		packageCards = append(packageCards, map[string]any{
			"fields": fields,
			"tags":   tags,
		})
	}
	payload := map[string]any{
		"deck_name":    record.DeckName,
		"model_name":   templateRow.Name,
		"field_names":  fieldNames,
		"qfmt":         templateRow.FrontHTML,
		"afmt":         templateRow.BackHTML,
		"css":          templateRow.CSS,
		"cards":        packageCards,
		"package_name": record.PackageName,
	}
	body, statusCode, err := ProxyJSON(ctx, deps.HTTPClient, deps.AnkiRuntimeURL, "/internal/anki/build-apkg", payload)
	if err != nil {
		fail("anki runtime unavailable")
		return
	}
	if statusCode < 200 || statusCode >= 300 {
		detail := strings.TrimSpace(string(body))
		if len(detail) > 240 {
			detail = detail[:240] + "..."
		}
		if detail != "" {
			fail(fmt.Sprintf("anki runtime build failed (%d): %s", statusCode, detail))
			return
		}
		fail(fmt.Sprintf("anki runtime build failed (%d)", statusCode))
		return
	}
	var resp struct {
		FileName   string `json:"file_name"`
		APKGBase64 string `json:"apkg_base64"`
	}
	if err := json.Unmarshal(body, &resp); err != nil {
		fail("invalid build-apkg response")
		return
	}
	if strings.TrimSpace(resp.APKGBase64) == "" {
		fail("empty package content")
		return
	}
	rawSize := base64.StdEncoding.DecodedLen(len(resp.APKGBase64))
	updateExportRecord(ctx, deps, record.SessionID, record.ExportID, func(cur apkgExportRecord) apkgExportRecord {
		cur.Status = "completed"
		cur.TemplateID = record.TemplateID
		cur.DeckName = record.DeckName
		cur.PackageName = record.PackageName
		cur.ConfirmedCount = record.ConfirmedCount
		cur.FileName = firstNonEmpty(strings.TrimSpace(resp.FileName), record.PackageName+".apkg")
		cur.FileSize = rawSize
		cur.APKGBase64 = resp.APKGBase64
		cur.Error = ""
		cur.CompletedAt = deps.NowRFC3339()
		cur.UpdatedAt = cur.CompletedAt
		return cur
	})
}

func resolveExportTemplateID(
	explicitTemplateID string,
	normalizedWorkspace map[string]any,
	resolveDefault func() (string, error),
) (string, error) {
	templateID := strings.TrimSpace(explicitTemplateID)
	if templateID != "" {
		return templateID, nil
	}
	templateID = strings.TrimSpace(valueFromAny(normalizedWorkspace["template_id"]))
	if templateID != "" {
		return templateID, nil
	}
	resolved, err := resolveDefault()
	if err != nil {
		return "", err
	}
	templateID = strings.TrimSpace(resolved)
	if templateID == "" {
		return "", fmt.Errorf("no default template")
	}
	return templateID, nil
}

func updateExportRecord(ctx context.Context, deps ExportsDeps, sessionID, exportID string, mutate func(apkgExportRecord) apkgExportRecord) {
	workspace, err := deps.ReadModel.LoadWorkspace(ctx, sessionID)
	if err != nil {
		return
	}
	if workspace == nil {
		return
	}
	exportsMap := ensureApkgExportMap(workspace)
	cur, ok := mapToExportRecord(exportsMap[exportID])
	if !ok {
		return
	}
	next := mutate(cur)
	exportsMap[exportID] = recordToMap(next)
	workspace["apkg_exports"] = exportsMap
	_ = deps.ReadModel.SaveWorkspace(ctx, sessionID, workspace)
}

func ensureApkgExportMap(workspace map[string]any) map[string]any {
	existing, ok := workspace["apkg_exports"].(map[string]any)
	if !ok || existing == nil {
		return map[string]any{}
	}
	return existing
}

func findExportRecord(workspace map[string]any, exportID, userID string) (apkgExportRecord, bool) {
	if workspace == nil {
		return apkgExportRecord{}, false
	}
	exportsMap := ensureApkgExportMap(workspace)
	raw, ok := exportsMap[exportID]
	if !ok {
		return apkgExportRecord{}, false
	}
	rec, ok := mapToExportRecord(raw)
	if !ok {
		return apkgExportRecord{}, false
	}
	if rec.UserID != userID {
		return apkgExportRecord{}, false
	}
	return rec, true
}

func sanitizeExportRecord(rec apkgExportRecord) map[string]any {
	return map[string]any{
		"export_id":       rec.ExportID,
		"session_id":      rec.SessionID,
		"template_id":     rec.TemplateID,
		"status":          rec.Status,
		"deck_name":       rec.DeckName,
		"package_name":    rec.PackageName,
		"confirmed_count": rec.ConfirmedCount,
		"file_name":       rec.FileName,
		"file_size":       rec.FileSize,
		"download_path":   rec.DownloadPath,
		"created_at":      rec.CreatedAt,
		"updated_at":      rec.UpdatedAt,
		"completed_at":    rec.CompletedAt,
		"error":           rec.Error,
	}
}

func recordToMap(rec apkgExportRecord) map[string]any {
	return map[string]any{
		"export_id":       rec.ExportID,
		"session_id":      rec.SessionID,
		"user_id":         rec.UserID,
		"template_id":     rec.TemplateID,
		"status":          rec.Status,
		"deck_name":       rec.DeckName,
		"package_name":    rec.PackageName,
		"confirmed_count": rec.ConfirmedCount,
		"file_name":       rec.FileName,
		"file_size":       rec.FileSize,
		"download_path":   rec.DownloadPath,
		"created_at":      rec.CreatedAt,
		"updated_at":      rec.UpdatedAt,
		"completed_at":    rec.CompletedAt,
		"error":           rec.Error,
		"apkg_base64":     rec.APKGBase64,
	}
}

func mapToExportRecord(raw any) (apkgExportRecord, bool) {
	m, ok := raw.(map[string]any)
	if !ok {
		return apkgExportRecord{}, false
	}
	rec := apkgExportRecord{
		ExportID:       valueFromAny(m["export_id"]),
		SessionID:      valueFromAny(m["session_id"]),
		UserID:         valueFromAny(m["user_id"]),
		TemplateID:     valueFromAny(m["template_id"]),
		Status:         valueFromAny(m["status"]),
		DeckName:       valueFromAny(m["deck_name"]),
		PackageName:    valueFromAny(m["package_name"]),
		ConfirmedCount: intFromAny(m["confirmed_count"]),
		FileName:       valueFromAny(m["file_name"]),
		FileSize:       intFromAny(m["file_size"]),
		DownloadPath:   valueFromAny(m["download_path"]),
		CreatedAt:      valueFromAny(m["created_at"]),
		UpdatedAt:      valueFromAny(m["updated_at"]),
		CompletedAt:    valueFromAny(m["completed_at"]),
		Error:          valueFromAny(m["error"]),
		APKGBase64:     valueFromAny(m["apkg_base64"]),
	}
	return rec, strings.TrimSpace(rec.ExportID) != "" && strings.TrimSpace(rec.SessionID) != ""
}

func filterConfirmedCards(cards []map[string]any) []map[string]any {
	out := make([]map[string]any, 0, len(cards))
	for _, c := range cards {
		editState, _ := c["edit_state"].(map[string]any)
		if strings.EqualFold(valueFromAny(editState["status"]), "confirmed") {
			out = append(out, c)
		}
	}
	return out
}

func pickTemplateIDFromCards(cards []map[string]any) string {
	counts := make(map[string]int)
	best := ""
	bestCount := 0
	for _, c := range cards {
		content, _ := c["content"].(map[string]any)
		model := strings.TrimSpace(valueFromAny(content["model"]))
		if model == "" {
			continue
		}
		counts[model]++
		if counts[model] > bestCount {
			bestCount = counts[model]
			best = model
		}
	}
	return best
}

func inferTemplateFieldNames(frontHTML, backHTML string) []string {
	joined := frontHTML + "\n" + backHTML
	matches := templateFieldPattern.FindAllStringSubmatch(joined, -1)
	seen := make(map[string]struct{})
	fields := make([]string, 0)
	for _, match := range matches {
		if len(match) < 2 {
			continue
		}
		name := normalizeTemplateToken(match[1])
		if name == "" {
			continue
		}
		if _, ok := seen[name]; ok {
			continue
		}
		seen[name] = struct{}{}
		fields = append(fields, name)
	}
	if _, ok := seen["Front"]; !ok {
		fields = append([]string{"Front"}, fields...)
		seen["Front"] = struct{}{}
	}
	if _, ok := seen["Back"]; !ok {
		fields = append(fields, "Back")
	}
	return fields
}

func normalizeTemplateToken(token string) string {
	s := strings.TrimSpace(token)
	if s == "" {
		return ""
	}
	s = strings.TrimPrefix(s, "#")
	s = strings.TrimPrefix(s, "/")
	s = strings.TrimPrefix(s, "^")
	if idx := strings.LastIndex(s, ":"); idx >= 0 {
		s = s[idx+1:]
	}
	if idx := strings.Index(s, "|"); idx >= 0 {
		s = s[:idx]
	}
	s = strings.TrimSpace(s)
	return s
}

func buildCardFields(card map[string]any, fieldNames []string, deckName string) (map[string]any, []string) {
	content, _ := card["content"].(map[string]any)
	data, _ := content["data"].(map[string]any)
	if data == nil {
		data = map[string]any{}
	}
	tags := extractTags(data["tags"])
	fields := make(map[string]any, len(fieldNames))
	for _, name := range fieldNames {
		switch name {
		case "Front":
			fields[name] = firstNonEmpty(valueFromAny(data["Front"]), valueFromAny(data["front"]))
		case "Back":
			fields[name] = firstNonEmpty(valueFromAny(data["Back"]), valueFromAny(data["back"]))
		case "Deck":
			fields[name] = firstNonEmpty(valueFromAny(data["Deck"]), deckName)
		case "Tags":
			fields[name] = firstNonEmpty(valueFromAny(data["Tags"]), strings.Join(tags, " "))
		default:
			fields[name] = pickFieldValue(data, name)
		}
	}
	return fields, tags
}

func pickFieldValue(data map[string]any, name string) string {
	if v, ok := data[name]; ok {
		return valueFromAny(v)
	}
	lower := strings.ToLower(name)
	for key, value := range data {
		if strings.ToLower(strings.TrimSpace(key)) == lower {
			return valueFromAny(value)
		}
	}
	return ""
}

func extractTags(raw any) []string {
	normalize := func(v string) string {
		v = strings.TrimSpace(v)
		if v == "" {
			return ""
		}
		v = strings.Join(strings.Fields(v), "_")
		return v
	}
	uniq := make(map[string]struct{})
	add := func(out []string, v string) []string {
		v = normalize(v)
		if v == "" {
			return out
		}
		if _, ok := uniq[v]; ok {
			return out
		}
		uniq[v] = struct{}{}
		return append(out, v)
	}

	switch t := raw.(type) {
	case []string:
		out := make([]string, 0, len(t))
		for _, v := range t {
			out = add(out, v)
		}
		sort.Strings(out)
		return out
	case []any:
		out := make([]string, 0, len(t))
		for _, item := range t {
			out = add(out, valueFromAny(item))
		}
		sort.Strings(out)
		return out
	default:
		v := strings.TrimSpace(valueFromAny(raw))
		if v == "" {
			return nil
		}
		parts := strings.FieldsFunc(v, func(r rune) bool { return r == ',' || r == ' ' || r == ';' })
		out := make([]string, 0, len(parts))
		for _, p := range parts {
			out = add(out, p)
		}
		sort.Strings(out)
		return out
	}
}

func sanitizeFileName(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return "session"
	}
	var b strings.Builder
	for _, r := range s {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '_' || r == '-' {
			b.WriteRune(r)
			continue
		}
		b.WriteRune('_')
	}
	return b.String()
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if strings.TrimSpace(v) != "" {
			return v
		}
	}
	return ""
}

func valueFromAny(v any) string {
	switch t := v.(type) {
	case string:
		return strings.TrimSpace(t)
	case fmt.Stringer:
		return strings.TrimSpace(t.String())
	case nil:
		return ""
	default:
		return strings.TrimSpace(fmt.Sprintf("%v", t))
	}
}
