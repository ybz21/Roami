package api

import (
	"reflect"
	"testing"
)

func TestOpenCodeActiveResponse(t *testing.T) {
	ids, err := openCodeActiveSessions([]byte(`{"data":{"ses_b":{"type":"running"},"ses_a":{"type":"running"}}}`))
	if err != nil || !reflect.DeepEqual(ids, []string{"ses_a", "ses_b"}) {
		t.Fatalf("active IDs = %v, %v", ids, err)
	}
	dir, err := openCodeSessionDirectory([]byte(`{"data":{"id":"ses_a","location":{"directory":"/work/project"}}}`))
	if err != nil || dir != "/work/project" {
		t.Fatalf("directory = %q, %v", dir, err)
	}
}

func TestOpenCodeActiveMapsOneSessionToOnePane(t *testing.T) {
	panes := map[string][]string{"/work/project": {"pane-b", "pane-a"}, "/work/other": {"pane-c"}}
	got := assignOpenCodePanes(panes, []string{"/work/project"})
	if !reflect.DeepEqual(got, map[string]bool{"pane-a": true}) {
		t.Fatalf("one active session assigned to %v", got)
	}
	got = assignOpenCodePanes(panes, []string{"/work/project", "/work/project"})
	if !reflect.DeepEqual(got, map[string]bool{"pane-a": true, "pane-b": true}) {
		t.Fatalf("two active sessions assigned to %v", got)
	}
}
