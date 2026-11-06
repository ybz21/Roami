package okr

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func htmlConfig(t *testing.T, project string) Config {
	t.Helper()
	root := filepath.Join(project, ".roami", "okr", "dashboard")
	if err := os.MkdirAll(root, 0700); err != nil {
		t.Fatal(err)
	}
	for name, content := range map[string]string{"index.html": `<!doctype html><html><head><link rel="stylesheet" href="style.css"><script defer src="page.js"></script></head><body><main>Approved</main></body></html>`, "style.css": `body { color: var(--text-bright) }`, "page.js": `window.okr.ready().then(() => window.okr.data.read('users'))`} {
		if err := os.WriteFile(filepath.Join(root, name), []byte(content), 0600); err != nil {
			t.Fatal(err)
		}
	}
	c := testConfig()
	c.Dashboard = &Dashboard{SchemaVersion: 2, HTML: &HTMLDashboard{Entry: "dashboard/index.html", Assets: []string{"dashboard/index.html", "dashboard/style.css", "dashboard/page.js"}, MetricIDs: []string{"users"}}}
	return c
}

func TestHTMLDashboardConfirmedAssetsAndDataRevisions(t *testing.T) {
	s, project := fileStore(t)
	w, err := s.Save("project", htmlConfig(t, project))
	if err != nil {
		t.Fatal(err)
	}
	if !w.ProjectFiles.HTMLDashboardSupported || w.ProjectFiles.PendingChanges || len(w.ProjectFiles.DashboardDigest) != 64 {
		t.Fatalf("metadata: %+v", w.ProjectFiles)
	}
	approved, _, err := s.Dashboard("project")
	if err != nil {
		t.Fatal(err)
	}
	entry := filepath.Join(project, ".roami", "okr", "dashboard", "index.html")
	if err := os.WriteFile(entry, []byte(`<main>Draft</main>`), 0600); err != nil {
		t.Fatal(err)
	}
	w, err = s.Get("project")
	if err != nil || !w.ProjectFiles.PendingChanges {
		t.Fatal(w, err)
	}
	w, err = s.Observe("project", w.Revision, "users", "2026-11-03", 0, "Observed zero")
	if err != nil {
		t.Fatal(err)
	}
	still, snapshot, err := s.Dashboard("project")
	if err != nil || still.Digest != approved.Digest || snapshot.Revision != w.Revision || len(snapshot.Observations) != 1 || snapshot.Observations[0].Value != 0 {
		t.Fatal(snapshot, err)
	}
	markup, err := still.Markup()
	if err != nil || !strings.Contains(markup, "Approved") || strings.Contains(markup, "Draft") || !strings.Contains(markup, "data:text/javascript;charset=utf-8;base64,") {
		t.Fatal(markup, err)
	}
	document, err := still.Document(strings.Repeat("a", 32))
	if err != nil || strings.Index(document, "function bootstrap") > strings.Index(document, "<link") || !strings.Contains(document, `"metricIds":["users"]`) {
		t.Fatal(document, err)
	}
	before := w.Revision
	if _, err := s.Sync("project", before-1); !errors.Is(err, ErrConflict) {
		t.Fatal(err)
	}
	w, err = s.Sync("project", before)
	if err != nil || w.ProjectFiles.PendingChanges || w.ProjectFiles.DashboardDigest == approved.Digest || len(w.Observations) != 1 {
		t.Fatal(w, err)
	}
	confirmed, _, err := s.Dashboard("project")
	if err != nil || !strings.Contains(string(confirmed.Assets["dashboard/index.html"].Body), "Draft") {
		t.Fatal(confirmed, err)
	}
	bundles, err := os.ReadDir(filepath.Join(project, ".roami", "okr", "state", "dashboard-assets"))
	if err != nil || len(bundles) != 2 {
		t.Fatal(bundles, err)
	}
	if _, err := confirmed.Document(`bad</script>`); !errors.Is(err, ErrInvalid) {
		t.Fatal(err)
	}
}

func TestHTMLDashboardRejectsInvalidPublishWithoutReplacingSnapshot(t *testing.T) {
	for _, content := range []string{
		`<script src="https://example.com/app.js"></script>`, `<script src="../agents/main.js"></script>`,
		`<script src="/dashboard/page.js"></script>`, `<script src="page.js?x=1"></script>`,
		`<iframe src="x"></iframe>`, `<meta http-equiv="refresh" content="0;url=https://example.com">`,
		`<form action="/api/agent/main-conversation"></form>`, `<img src="https://example.com/image.png">`,
		`<link rel="preload" href="page.js">`, `<img srcset="page.js">`,
	} {
		t.Run(content, func(t *testing.T) {
			s, project := fileStore(t)
			w, err := s.Save("project", htmlConfig(t, project))
			if err != nil {
				t.Fatal(err)
			}
			before := w.ProjectFiles.DashboardDigest
			if err := os.WriteFile(filepath.Join(project, ".roami", "okr", "dashboard", "index.html"), []byte(content), 0600); err != nil {
				t.Fatal(err)
			}
			if _, err := s.Sync("project", w.Revision); !errors.Is(err, ErrInvalid) {
				t.Fatal(err)
			}
			bundle, current, err := s.Dashboard("project")
			if err != nil || bundle.Digest != before || current.Revision != w.Revision {
				t.Fatal(current, err)
			}
		})
	}
}

func TestHTMLDashboardRejectsSiblingSymlinkAndTamperedBundle(t *testing.T) {
	s, project := fileStore(t)
	c := htmlConfig(t, project)
	root := filepath.Join(project, ".roami", "okr")
	page := filepath.Join(root, "dashboard", "page.js")
	if err := os.Remove(page); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "private.js"), []byte("private"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("../private.js", page); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Save("project", c); !errors.Is(err, ErrInvalid) {
		t.Fatal(err)
	}
	if err := os.Remove(page); err != nil {
		t.Fatal(err)
	}
	w, err := s.Save("project", htmlConfig(t, project))
	if err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(root, "state", "dashboard-assets", w.ProjectFiles.DashboardDigest+".json")
	editJSON(t, file, func(v map[string]any) { v["entry"] = "dashboard/another.html" })
	if _, _, err := s.Dashboard("project"); !errors.Is(err, ErrInvalid) {
		t.Fatal(err)
	}
}

func TestHTMLDashboardValidatesBindingsAndStorage(t *testing.T) {
	s, project := fileStore(t)
	for _, mutate := range []func(*HTMLDashboard){
		func(h *HTMLDashboard) { h.Entry = "../index.html" },
		func(h *HTMLDashboard) { h.Assets = append(h.Assets, h.Entry) },
		func(h *HTMLDashboard) { h.MetricIDs = []string{"other-project"} },
		func(h *HTMLDashboard) { h.Libraries = []string{"https://cdn.example.com/chart.js"} },
	} {
		c := htmlConfig(t, project)
		mutate(c.Dashboard.HTML)
		if _, err := s.Save("project", c); !errors.Is(err, ErrInvalid) {
			t.Fatal(err)
		}
	}
	legacy, _ := testStore(t)
	if _, err := legacy.Save("project", htmlConfig(t, project)); !errors.Is(err, ErrInvalid) {
		t.Fatal(err)
	}
}
