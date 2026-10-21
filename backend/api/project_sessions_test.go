package api

import (
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/ttmux"
)

func TestProjectMembershipIncludesSessionsBeyondTopThree(t *testing.T) {
	_, tmp, tmux := e2eSetup(t)
	repo := e2eRepo(t, tmp)
	h := New(ttmux.New(filepath.Join(tmp, "roami-e2e")), "", tmp, "")
	id := h.Projects.Touch(repo)
	for i := 0; i < 6; i++ {
		tmux("new-session", "-d", "-s", fmt.Sprintf("member-%d", i), "-c", repo)
	}
	r := gin.New()
	r.GET("/projects", h.ProjectsList)
	req := httptest.NewRequest("GET", "/projects?sessionProject="+id, nil)
	response := httptest.NewRecorder()
	r.ServeHTTP(response, req)
	if response.Code != 200 {
		t.Fatalf("membership: %d %s", response.Code, response.Body)
	}
	var result struct {
		Data struct {
			Sessions []projectSession `json:"sessions"`
		} `json:"data"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if len(result.Data.Sessions) != 6 {
		t.Fatalf("full membership lost rows: %+v", result.Data.Sessions)
	}
	if result.Data.Sessions[5].Name != "member-5" {
		t.Fatalf("sixth session not discoverable: %+v", result.Data.Sessions)
	}
}
