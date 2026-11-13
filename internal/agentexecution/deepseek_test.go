package agentexecution

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"testing"
)

func TestDeepSeekHeadlessResultAndFailure(t *testing.T) {
	for _, exit := range []string{"0", "9"} {
		t.Run(exit, func(t *testing.T) {
			service := testService(t)
			dir, _ := service.directory("headless")
			if err := os.MkdirAll(dir, 0700); err != nil {
				t.Fatal(err)
			}
			script := "#!/bin/sh\n[ \"$#\" = 3 ] && [ \"$1\" = --profile ] && [ \"$2\" = headless ] || exit 99\n[ \"$3\" = - ] && [ \"$(/bin/cat)\" = \"$EXPECTED_TASK\" ] || exit 98\nprintf 'DSH final answer'\nprintf 'DSH reasoning' >&2\nexit " + exit + "\n"
			if err := os.WriteFile(filepath.Join(dir, "dsh"), []byte(script), 0700); err != nil {
				t.Fatal(err)
			}
			t.Setenv("PATH", dir)
			prompt := "Read John's file\nKeep $(this) and `that` literal"
			t.Setenv("EXPECTED_TASK", prompt)
			spec := Spec{Key: "headless", Executor: "deepseek", Directory: dir, Prompt: prompt}
			if err := writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
				t.Fatal(err)
			}
			if err := writeJSON(filepath.Join(dir, "receipt.json"), Receipt{State: "launched"}); err != nil {
				t.Fatal(err)
			}
			if err := service.Run(context.Background(), spec.Key, io.Discard, io.Discard); err != nil {
				t.Fatal(err)
			}
			status, err := service.Status(spec.Key)
			want := "succeeded"
			if exit != "0" {
				want = "failed"
			}
			if err != nil || status.Result == nil || status.State != want || status.Result.Summary != "DSH final answer" || status.Result.Stderr != "DSH reasoning" {
				t.Fatalf("wrong result: %+v, %v", status, err)
			}
		})
	}
}

func TestDeepSeekRejectsPersistentLaunchBeforeCreatingResources(t *testing.T) {
	service := testService(t)
	_, err := service.Launch(context.Background(), Spec{Key: "persistent", Executor: "deepseek", Persistent: true, Directory: t.TempDir(), Prompt: "work"})
	if err == nil || err.Error() != "EXECUTOR_PERSISTENCE_UNSUPPORTED" {
		t.Fatalf("unsupported persistent launch: %v", err)
	}
	dir, _ := service.directory("persistent")
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatal("rejected launch created resources")
	}
}
