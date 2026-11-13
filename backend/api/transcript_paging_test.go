package api

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestTranscriptPagesStartAtNewestAndReadOlderWithoutGaps(t *testing.T) {
	for _, executor := range []string{"claude", "codex"} {
		t.Run(executor, func(t *testing.T) {
			name, file, _ := managedHistoryFixture(t, executor)
			var content strings.Builder
			for i := 0; i < 275; i++ {
				if executor == "claude" {
					fmt.Fprintf(&content, "{\"type\":\"assistant\",\"uuid\":\"message-%d\",\"message\":{\"content\":[{\"type\":\"text\",\"text\":\"message-%d\"}]}}\n", i, i)
				} else {
					fmt.Fprintf(&content, "{\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"assistant\",\"content\":[{\"type\":\"output_text\",\"text\":\"message-%d\"}]}}\n", i)
				}
			}
			if err := os.WriteFile(file, []byte(content.String()), 0600); err != nil {
				t.Fatal(err)
			}
			r := gin.New()
			handler := (&API{}).ClaudeTranscript
			if executor == "codex" {
				handler = (&API{}).CodexTranscript
			}
			r.GET("/sessions/:name/history", handler)
			type pageData struct {
				Messages   []cMsg `json:"messages"`
				Before     int64  `json:"before"`
				NextOffset int64  `json:"nextOffset"`
				Truncated  bool   `json:"truncated"`
			}
			get := func(query string) pageData {
				t.Helper()
				w := httptest.NewRecorder()
				r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/sessions/"+name+"/history?boff=1&"+query, nil))
				var result struct {
					Data pageData `json:"data"`
				}
				if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil || w.Code != http.StatusOK {
					t.Fatalf("page: %v %d %s", err, w.Code, w.Body.String())
				}
				return result.Data
			}
			first := get("")
			if len(first.Messages) != defaultTranscriptTail || first.Messages[0].Blocks[0].Text != "message-225" || !first.Truncated {
				t.Fatalf("first page must contain only newest records: %+v", first)
			}
			// A stale cursor after truncation must also return a bounded newest page.
			reset := get("offset=" + strconv.Itoa(content.Len()+100))
			if len(reset.Messages) != defaultTranscriptTail || reset.Messages[0].Blocks[0].Text != "message-225" {
				t.Fatalf("reset loaded unbounded history: %+v", reset)
			}
			all := first.Messages
			page := first
			for page.Truncated {
				previous := page.Before
				page = get("before=" + strconv.FormatInt(previous, 10))
				if len(page.Messages) > defaultTranscriptTail || page.Before >= previous {
					t.Fatalf("older page failed to advance within its batch: %+v", page)
				}
				all = append(page.Messages, all...)
			}
			if len(all) != 275 {
				t.Fatalf("page count = %d", len(all))
			}
			for i, message := range all {
				if message.Blocks[0].Text != fmt.Sprintf("message-%d", i) {
					t.Fatalf("gap or duplicate at %d: %+v", i, message)
				}
			}
			if got := get("offset=" + strconv.FormatInt(first.NextOffset, 10)); len(got.Messages) != 0 || got.NextOffset != first.NextOffset {
				t.Fatalf("unchanged poll reread history: %+v", got)
			}
		})
	}
}
