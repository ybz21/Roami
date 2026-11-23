package agentexecution

import (
	"context"
	"os"
	"testing"
)

func TestRetiredExecutorRejectsLaunchBeforeCreatingResources(t *testing.T) {
	for _, kind := range []string{"deepseek", "gemini"} {
		t.Run(kind, func(t *testing.T) {
			for _, persistent := range []bool{false, true} {
				service := testService(t)
				_, err := service.Launch(context.Background(), Spec{Key: "retired", Executor: kind, Persistent: persistent, Directory: t.TempDir(), Prompt: "work"})
				if err == nil || err.Error() != "INVALID_EXECUTOR" {
					t.Fatalf("persistent=%v: retired executor accepted: %v", persistent, err)
				}
				dir, _ := service.directory("retired")
				if _, err := os.Stat(dir); !os.IsNotExist(err) {
					t.Fatal("rejected launch created resources")
				}
			}
		})
	}
	for _, candidate := range DiscoverExecutors().Candidates {
		if candidate.Kind == "deepseek" || candidate.Kind == "gemini" {
			t.Fatal("retired executor still advertised")
		}
	}
}
