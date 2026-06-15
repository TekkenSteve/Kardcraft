package architecture

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestGoAgentImportsStayBehindAdapterBoundary(t *testing.T) {
	root := repositoryRoot(t)
	allowedPrefixes := []string{
		filepath.Join(root, "cmd", "worker") + string(filepath.Separator),
		filepath.Join(root, "internal", "adapter", "goagent") + string(filepath.Separator),
		filepath.Join(root, "internal", "app") + string(filepath.Separator),
	}
	forbiddenImports := []string{
		`"github.com/TekkenSteve/GoAgent/agentfw`,
		`"github.com/TekkenSteve/GoAgent/entity`,
		`"github.com/TekkenSteve/GoAgent/pkg`,
		`"github.com/TekkenSteve/GoAgent/repo`,
		`"github.com/TekkenSteve/GoAgent/usecase`,
	}

	err := filepath.WalkDir(root, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() {
			switch entry.Name() {
			case ".git", "bin":
				return filepath.SkipDir
			}
			return nil
		}
		if filepath.Ext(path) != ".go" || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		content := string(data)
		if !strings.Contains(content, `"github.com/TekkenSteve/GoAgent/`) {
			return nil
		}
		if !hasAllowedPrefix(path, allowedPrefixes) {
			t.Errorf("GoAgent import outside adapter/composition boundary: %s", relPath(root, path))
		}
		for _, forbidden := range forbiddenImports {
			if strings.Contains(content, forbidden) {
				t.Errorf("forbidden GoAgent internal import %s in %s", forbidden, relPath(root, path))
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}

func repositoryRoot(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatal("go.mod not found")
		}
		dir = parent
	}
}

func hasAllowedPrefix(path string, prefixes []string) bool {
	for _, prefix := range prefixes {
		if strings.HasPrefix(path, prefix) {
			return true
		}
	}
	return false
}

func relPath(root, path string) string {
	rel, err := filepath.Rel(root, path)
	if err != nil {
		return path
	}
	return rel
}
