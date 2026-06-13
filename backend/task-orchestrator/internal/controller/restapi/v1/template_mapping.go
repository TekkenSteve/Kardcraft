package v1

import (
	"strconv"
	"strings"
)

func StringOrDefault(v any, d string) string {
	s, _ := v.(string)
	s = strings.TrimSpace(s)
	if s == "" {
		return d
	}
	return s
}

func IntOrDefault(v any, d int) int {
	switch n := v.(type) {
	case int:
		return n
	case int64:
		return int(n)
	case float64:
		return int(n)
	case string:
		if parsed, err := strconv.Atoi(n); err == nil {
			return parsed
		}
	}
	return d
}

func MapFromAny(v any) map[string]any {
	if v == nil {
		return nil
	}
	if m, ok := v.(map[string]any); ok {
		return m
	}
	return nil
}

func StringSliceFromAny(v any) []string {
	out := make([]string, 0)
	if v == nil {
		return out
	}
	raw, ok := v.([]any)
	if !ok {
		if typed, ok := v.([]string); ok {
			for _, item := range typed {
				s := strings.TrimSpace(item)
				if s != "" {
					out = append(out, s)
				}
			}
		}
		return out
	}
	for _, item := range raw {
		s, ok := item.(string)
		if !ok {
			continue
		}
		s = strings.TrimSpace(s)
		if s != "" {
			out = append(out, s)
		}
	}
	return out
}

func ExtractTemplateProfiles(mappingSpec map[string]any) ([]string, string) {
	profiles := make([]string, 0)
	seen := make(map[string]struct{})
	defaultProfile := strings.TrimSpace(StringOrDefault(mappingSpec["default_profile"], ""))
	rawProfiles, _ := mappingSpec["profiles"].([]any)
	for _, entry := range rawProfiles {
		if item, ok := entry.(map[string]any); ok {
			name := strings.TrimSpace(StringOrDefault(item["name"], ""))
			if name == "" {
				continue
			}
			if _, exists := seen[name]; exists {
				continue
			}
			seen[name] = struct{}{}
			profiles = append(profiles, name)
			continue
		}
		if name, ok := entry.(string); ok {
			name = strings.TrimSpace(name)
			if name == "" {
				continue
			}
			if _, exists := seen[name]; exists {
				continue
			}
			seen[name] = struct{}{}
			profiles = append(profiles, name)
		}
	}
	if defaultProfile == "" && len(profiles) > 0 {
		defaultProfile = profiles[0]
	}
	if defaultProfile != "" {
		if _, exists := seen[defaultProfile]; !exists {
			profiles = append(profiles, defaultProfile)
		}
	}
	return profiles, defaultProfile
}

func ResolveSampleFieldsFromMapping(mappingSpec map[string]any, profile string) (map[string]any, bool) {
	rawProfiles, _ := mappingSpec["profiles"].([]any)
	for _, entry := range rawProfiles {
		item, ok := entry.(map[string]any)
		if !ok {
			continue
		}
		name := strings.TrimSpace(StringOrDefault(item["name"], ""))
		if name == "" {
			continue
		}
		if profile != "" && name != profile {
			continue
		}
		if sample, ok := item["sample_fields"].(map[string]any); ok && len(sample) > 0 {
			return sample, true
		}
	}
	return nil, false
}
