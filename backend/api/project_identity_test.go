package api

import (
	"encoding/json"
	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/project"
	"net/http/httptest"
	"testing"
)

func TestProjectIdentityDoesNotNeedSessionOrWorktreeScanner(t *testing.T) {
	store := project.NewStore(t.TempDir(), nil)
	dir := t.TempDir()
	id := store.Touch(dir)
	a := &API{Projects: store}
	r := gin.New()
	r.GET("/projects", a.ProjectsList)
	response := httptest.NewRecorder()
	r.ServeHTTP(response, httptest.NewRequest("GET", "/projects?identity="+id, nil))
	if response.Code != 200 {
		t.Fatalf("identity: %d %s", response.Code, response.Body)
	}
	var result struct {
		Data struct {
			Projects []struct {
				Key string `json:"key"`
				Dir string `json:"dir"`
			} `json:"projects"`
		} `json:"data"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if len(result.Data.Projects) != 1 || result.Data.Projects[0].Key != id || result.Data.Projects[0].Dir != dir {
		t.Fatalf("wrong identity: %+v", result)
	}
	response = httptest.NewRecorder()
	r.ServeHTTP(response, httptest.NewRequest("GET", "/projects?identity=missing", nil))
	if response.Code != 404 {
		t.Fatalf("missing identity: %d", response.Code)
	}
}
