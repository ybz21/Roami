package api

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestAgentCapabilitiesCreatesEditableGuide(t *testing.T) {
	isolateTestStorage(t, t.TempDir())
	path := filepath.Join(os.Getenv("ROAMI_HOME"), agentCapabilitiesFile)
	initial, err := readAgentCapabilities()
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(initial, "{{FILE_BASE}}/tmp/report.md") || !strings.Contains(initial, "{{FILE_RAW_BASE}}?path=") || !strings.Contains(initial, "roami chrome tabs") {
		t.Fatalf("default guide missing capabilities: %q", initial)
	}
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0o600 {
		t.Fatalf("guide permissions: %v %v", info, err)
	}
	if err := os.WriteFile(path, []byte("我的自定义能力"), 0o600); err != nil {
		t.Fatal(err)
	}
	got, err := readAgentCapabilities()
	if err != nil || got != "我的自定义能力" {
		t.Fatalf("custom guide overwritten: %q %v", got, err)
	}
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/agent/capabilities", (&API{}).AgentCapabilities)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/agent/capabilities", nil))
	if w.Code != http.StatusOK || !strings.Contains(w.Body.String(), "我的自定义能力") {
		t.Fatalf("GET guide: %d %s", w.Code, w.Body.String())
	}
}

func TestAgentCapabilitiesUpgradesShippedGuides(t *testing.T) {
	want, err := defaultAgentCapabilities.ReadFile("prompts/" + agentCapabilitiesFile)
	if err != nil {
		t.Fatal(err)
	}
	files, err := filepath.Glob("testdata/agent-capabilities/*.txt")
	if err != nil || len(files) != 4 {
		t.Fatalf("historical guides: %v %v", files, err)
	}
	for _, file := range files {
		t.Run(filepath.Base(file), func(t *testing.T) {
			isolateTestStorage(t, t.TempDir())
			path := agentCapabilitiesPath()
			old, err := os.ReadFile(file)
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, old, 0o600); err != nil {
				t.Fatal(err)
			}
			for i := 0; i < 2; i++ {
				got, err := readAgentCapabilities()
				if err != nil || got != string(want) {
					t.Fatalf("read %d: guide not upgraded: %v", i, err)
				}
			}
			stored, err := os.ReadFile(path)
			if err != nil || string(stored) != string(want) {
				t.Fatalf("upgraded guide not saved: %v", err)
			}
			info, err := os.Stat(path)
			if err != nil || info.Mode().Perm() != 0o600 {
				t.Fatalf("upgraded guide permissions: %v %v", info, err)
			}
		})
	}
}

func TestAgentCapabilitiesPreservesEditedLegacyGuide(t *testing.T) {
	isolateTestStorage(t, t.TempDir())
	old, err := os.ReadFile("testdata/agent-capabilities/original.txt")
	if err != nil {
		t.Fatal(err)
	}
	custom := string(old) + "\n我的项目专用说明\n"
	if err := os.WriteFile(agentCapabilitiesPath(), []byte(custom), 0o600); err != nil {
		t.Fatal(err)
	}
	got, err := readAgentCapabilities()
	if err != nil || got != custom {
		t.Fatalf("edited guide overwritten: %v", err)
	}
}
