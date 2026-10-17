package session

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"testing"

	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

func resolutionRuntime(t *testing.T, output string, exit int) runtime.Runtime {
	t.Helper()
	dir := t.TempDir()
	state := filepath.Join(dir, "snapshot")
	if err := os.WriteFile(state, []byte(output), 0600); err != nil {
		t.Fatal(err)
	}
	bin := filepath.Join(dir, "tmux")
	code := "#!/bin/sh\ncat '" + state + "'\nexit " + strconv.Itoa(exit) + "\n"
	if err := os.WriteFile(bin, []byte(code), 0700); err != nil {
		t.Fatal(err)
	}
	return runtime.Runtime{TmuxBin: bin, DataDir: dir, HomeDir: dir}
}

func TestLiveIdentitySnapshotAndStrictCLIResolution(t *testing.T) {
	rt := resolutionRuntime(t, "$0\t1785233330\t2026-0728-1808-0000\tsame\n"+
		"$1\t1785233330\t2026-0728-1808-0001\tsame\n", 0)
	var output bytes.Buffer
	if err := ListLiveJSON(rt, map[string]bool{"2026-0728-1808-0000": true}, &output); err != nil {
		t.Fatal(err)
	}
	var items []map[string]string
	if err := json.Unmarshal(output.Bytes(), &items); err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0]["id"] != "2026-0728-1808-0001" || items[0]["state"] != "live" {
		t.Fatalf("unexpected identities: %+v", items)
	}
	output.Reset()
	if err := Resolve(rt, []string{"same", "--strict", "--json"}, &output); err == nil || err.Error() != "SESSION_TARGET_AMBIGUOUS" || output.Len() != 0 {
		t.Fatalf("ambiguous resolution emitted success: %s %v", output.String(), err)
	}
	if err := Resolve(rt, []string{"$1", "--strict", "--json"}, &output); err != nil {
		t.Fatal(err)
	}
	var resolved map[string]string
	if err := json.Unmarshal(output.Bytes(), &resolved); err != nil || resolved["id"] != "2026-0728-1808-0001" {
		t.Fatalf("strict resolution: %s %v", output.String(), err)
	}
}

func TestLiveSnapshotFailureIsNotAnEmptyList(t *testing.T) {
	var output bytes.Buffer
	err := ListLiveJSON(resolutionRuntime(t, "transport unavailable", 1), nil, &output)
	if err == nil || err.Error() != "SESSION_OBSERVATION_FAILED" || output.Len() != 0 {
		t.Fatalf("failure returned data: %s %v", output.String(), err)
	}
	if err := ListLiveJSON(resolutionRuntime(t, "no server running on /tmp/test", 1), nil, &output); err != nil || output.String() != "[]\n" {
		t.Fatalf("known empty server: %s %v", output.String(), err)
	}
}
