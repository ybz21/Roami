package api

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ybz21/Roami/backend/okr"
)

func TestHTMLDashboardAPIRequiresConfirmedProjectAndDigest(t *testing.T) {
	a, router, id := projectOKRFixture(t)
	router.GET("/projects/:key/okr/dashboard", a.ProjectOKRDashboard)
	router.GET("/projects/:key/okr/dashboard/document", a.ProjectOKRDashboardDocument)
	base := "/projects/" + id + "/okr/dashboard"
	projectOKRRequest(t, router, "GET", base, "", 404)
	entry, _ := a.Projects.Entry(id)
	dir := filepath.Join(entry.Dir, ".roami", "okr", "dashboard")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "index.html"), []byte(`<main>Project chart</main>`), 0600); err != nil {
		t.Fatal(err)
	}
	var c okr.Config
	if err := json.Unmarshal([]byte(projectOKRConfigJSON()), &c); err != nil {
		t.Fatal(err)
	}
	c.Dashboard = &okr.Dashboard{SchemaVersion: 2, HTML: &okr.HTMLDashboard{Entry: "dashboard/index.html", Assets: []string{"dashboard/index.html"}, MetricIDs: []string{"users"}}}
	body, _ := json.Marshal(c)
	w := decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", "/projects/"+id+"/okr", string(body), 200))
	response := projectOKRRequest(t, router, "GET", base, "", 200)
	if strings.Contains(response.Body.String(), "assets") || strings.Contains(response.Body.String(), "Project chart") || !strings.Contains(response.Body.String(), w.ProjectFiles.DashboardDigest) {
		t.Fatal(response.Body.String())
	}
	nonce := strings.Repeat("b", 32)
	documentPath := base + "/document?digest=" + w.ProjectFiles.DashboardDigest + "&nonce=" + nonce
	response = projectOKRRequest(t, router, "GET", documentPath, "", 200)
	if response.Header().Get("Cache-Control") != "no-store" || response.Header().Get("Referrer-Policy") != "no-referrer" || response.Header().Get("X-Content-Type-Options") != "nosniff" {
		t.Fatal(response.Header())
	}
	policy := response.Header().Get("Content-Security-Policy")
	for _, directive := range []string{"sandbox allow-scripts", "connect-src 'none'", "frame-ancestors 'self'", "form-action 'none'"} {
		if !strings.Contains(policy, directive) {
			t.Fatal(policy)
		}
	}
	if strings.Contains(policy, "allow-same-origin") || !strings.Contains(response.Body.String(), nonce) || !strings.Contains(response.Body.String(), "Project chart") {
		t.Fatal(policy, response.Body.String())
	}
	projectOKRRequest(t, router, "GET", base+"/document?digest=old&nonce="+nonce, "", 409)
	projectOKRRequest(t, router, "GET", base+"/document?digest="+w.ProjectFiles.DashboardDigest+"&nonce=bad", "", 400)
	other, _ := a.Projects.Add(t.TempDir(), "Other")
	projectOKRRequest(t, router, "GET", "/projects/"+other+"/okr/dashboard/document?digest="+w.ProjectFiles.DashboardDigest+"&nonce="+nonce, "", 404)
	if err := os.WriteFile(filepath.Join(dir, "index.html"), []byte(`<script src="https://example.com/draft.js"></script>`), 0600); err != nil {
		t.Fatal(err)
	}
	response = projectOKRRequest(t, router, "GET", documentPath, "", 200)
	if strings.Contains(response.Body.String(), "draft.js") {
		t.Fatal("unconfirmed code served")
	}
}
