// Package hydra adapts Ory Hydra RFC 7662 token introspection to Kardcraft's
// internal service-authentication boundary.
package hydra

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"
)

type IntrospectionConfig struct {
	Endpoint         string
	ClientID         string
	ClientSecret     string
	RequiredScope    string
	RequiredClient   string
	RequiredAudience string
}

type Introspector struct {
	client *http.Client
	config IntrospectionConfig
}

func NewIntrospector(client *http.Client, config IntrospectionConfig) (*Introspector, error) {
	config.Endpoint = strings.TrimSpace(config.Endpoint)
	config.ClientID = strings.TrimSpace(config.ClientID)
	config.ClientSecret = strings.TrimSpace(config.ClientSecret)
	config.RequiredScope = strings.TrimSpace(config.RequiredScope)
	config.RequiredClient = strings.TrimSpace(config.RequiredClient)
	config.RequiredAudience = strings.TrimSpace(config.RequiredAudience)
	if config.Endpoint == "" || config.ClientID == "" || config.ClientSecret == "" || config.RequiredScope == "" || config.RequiredClient == "" || config.RequiredAudience == "" {
		return nil, fmt.Errorf("hydra introspection configuration is incomplete")
	}
	if client == nil {
		client = http.DefaultClient
	}

	return &Introspector{client: client, config: config}, nil
}

func (i *Introspector) Validate(ctx context.Context, token string) error {
	if i == nil {
		return fmt.Errorf("hydra introspector is required")
	}
	token = strings.TrimSpace(token)
	if token == "" {
		return fmt.Errorf("bearer token is required")
	}
	form := url.Values{"token": []string{token}}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, i.config.Endpoint, strings.NewReader(form.Encode()))
	if err != nil {
		return fmt.Errorf("create hydra introspection request: %w", err)
	}
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	request.SetBasicAuth(i.config.ClientID, i.config.ClientSecret)
	response, err := i.client.Do(request)
	if err != nil {
		return fmt.Errorf("hydra introspection request: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("hydra introspection returned %s", response.Status)
	}
	var result introspectionResponse
	if err := json.NewDecoder(response.Body).Decode(&result); err != nil {
		return fmt.Errorf("decode hydra introspection response: %w", err)
	}
	if !result.Active || result.ClientID != i.config.RequiredClient || !hasScope(result.Scope, i.config.RequiredScope) || !hasAudience(result.Audience, i.config.RequiredAudience) {
		return fmt.Errorf("service token does not satisfy execution event policy")
	}

	return nil
}

type introspectionResponse struct {
	Active   bool     `json:"active"`
	ClientID string   `json:"client_id"`
	Scope    string   `json:"scope"`
	Audience []string `json:"aud"`
}

func hasScope(scopes, required string) bool {
	for _, scope := range strings.Fields(scopes) {
		if scope == required {
			return true
		}
	}
	return false
}

func hasAudience(audiences []string, required string) bool {
	for _, audience := range audiences {
		if audience == required {
			return true
		}
	}
	return false
}
