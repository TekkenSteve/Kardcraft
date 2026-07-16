// Package anki implements the outbound boundary for Kardcraft's Anki runtime.
package anki

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"

	"task-orchestrator/internal/usecase"
)

type Client struct {
	httpClient *http.Client
	baseURL    string
}

// BuildAPKG is the typed APKG construction boundary used by the export
// application workflow. HTTP response details do not leak above this adapter.
func (c *Client) BuildAPKG(ctx context.Context, request usecase.BuildAPKGRequest) (usecase.BuildAPKGResult, error) {
	payload := map[string]any{
		"deck_name": request.DeckName, "model_name": request.ModelName, "field_names": request.FieldNames,
		"qfmt": request.FrontHTML, "afmt": request.BackHTML, "css": request.CSS, "package_name": request.PackageName,
	}
	cards := make([]map[string]any, 0, len(request.Cards))
	for _, card := range request.Cards {
		cards = append(cards, map[string]any{"fields": card.Fields, "tags": card.Tags})
	}
	payload["cards"] = cards
	body, statusCode, err := c.PostJSON(ctx, "/internal/anki/build-apkg", payload)
	if err != nil {
		return usecase.BuildAPKGResult{}, fmt.Errorf("request Anki APKG build: %w", err)
	}
	if statusCode < http.StatusOK || statusCode >= http.StatusMultipleChoices {
		detail := strings.TrimSpace(string(body))
		if len(detail) > 240 {
			detail = detail[:240]
		}
		return usecase.BuildAPKGResult{}, fmt.Errorf("Anki APKG build failed (%d): %s", statusCode, detail)
	}
	var response struct {
		FileName   string `json:"file_name"`
		APKGBase64 string `json:"apkg_base64"`
	}
	if err := json.Unmarshal(body, &response); err != nil {
		return usecase.BuildAPKGResult{}, fmt.Errorf("decode Anki APKG build response: %w", err)
	}
	content, err := base64.StdEncoding.DecodeString(strings.TrimSpace(response.APKGBase64))
	if err != nil || len(content) == 0 {
		return usecase.BuildAPKGResult{}, fmt.Errorf("Anki APKG build response has no package content")
	}
	return usecase.BuildAPKGResult{FileName: strings.TrimSpace(response.FileName), Content: content}, nil
}

func NewClient(httpClient *http.Client, baseURL string) (*Client, error) {
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	baseURL = strings.TrimRight(strings.TrimSpace(baseURL), "/")
	if baseURL == "" {
		return nil, fmt.Errorf("anki runtime URL is required")
	}

	return &Client{httpClient: httpClient, baseURL: baseURL}, nil
}

func (c *Client) PostJSON(ctx context.Context, path string, payload any) ([]byte, int, error) {
	if c == nil {
		return nil, 0, fmt.Errorf("anki client is required")
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return nil, 0, fmt.Errorf("encode Anki request: %w", err)
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+path, strings.NewReader(string(encoded)))
	if err != nil {
		return nil, 0, fmt.Errorf("create Anki request: %w", err)
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := c.httpClient.Do(request)
	if err != nil {
		return nil, 0, fmt.Errorf("send Anki request: %w", err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		return nil, 0, fmt.Errorf("read Anki response: %w", err)
	}

	return body, response.StatusCode, nil
}

// ExecuteTemplateRuntime maps the typed application operation to the Anki
// runtime protocol. Endpoint paths do not leak into HTTP controllers.
func (c *Client) ExecuteTemplateRuntime(ctx context.Context, operation usecase.TemplateOperation, payload map[string]any) (usecase.TemplateOperationResult, error) {
	paths := map[usecase.TemplateOperation]string{
		usecase.TemplateOperationPreview:        "/internal/anki/preview",
		usecase.TemplateOperationValidate:       "/internal/anki/validate-template",
		usecase.TemplateOperationRequiredFields: "/internal/anki/required-fields",
		usecase.TemplateOperationPrecheck:       "/internal/anki/precheck",
		usecase.TemplateOperationBuildAPKG:      "/internal/anki/build-apkg",
	}
	path, exists := paths[operation]
	if !exists {
		return usecase.TemplateOperationResult{}, fmt.Errorf("unsupported template operation: %s", operation)
	}
	body, statusCode, err := c.PostJSON(ctx, path, payload)
	if err != nil {
		return usecase.TemplateOperationResult{}, err
	}
	return usecase.TemplateOperationResult{StatusCode: statusCode, Body: body}, nil
}
