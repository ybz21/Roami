package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/okr"
)

func TestOKRMemoryCapacityIsActionableConflict(t *testing.T) {
	recorder := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(recorder)
	okrError(c, &okr.MemoryCapacityError{CurrentBytes: 64356, RequestedBytes: 67000, LimitBytes: 65536})
	var result struct {
		Error          string `json:"error"`
		CurrentBytes   int    `json:"currentBytes"`
		RequestedBytes int    `json:"requestedBytes"`
		LimitBytes     int    `json:"limitBytes"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if recorder.Code != http.StatusConflict || result.Error != "OKR_MEMORY_CAPACITY" || result.CurrentBytes != 64356 || result.RequestedBytes != 67000 || result.LimitBytes != 65536 {
		t.Fatalf("unactionable response: %d %+v", recorder.Code, result)
	}
}
