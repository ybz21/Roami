package gitcontext

import (
	"reflect"
	"testing"
)

func TestDirectoryBindingIsRemovedWithoutLosingGitAuthentication(t *testing.T) {
	input := []string{"GIT_DIR=/caller/.git", "GIT_WORK_TREE=/caller", "GIT_INDEX_FILE=/caller/index",
		"GIT_IMPLICIT_WORK_TREE=0", "GIT_SHALLOW_FILE=/caller/shallow", "GIT_NAMESPACE=caller",
		"GIT_SSH_COMMAND=ssh -i /account/key", "GIT_TERMINAL_PROMPT=0", "GIT_AUTHOR_NAME=Author", "PATH=/bin"}
	original := append([]string(nil), input...)
	want := input[6:]
	if got := ForDirectory(input); !reflect.DeepEqual(got, want) {
		t.Fatalf("repository binding/authentication boundary: %v", got)
	}
	if !reflect.DeepEqual(input, original) {
		t.Fatal("the caller's environment was mutated")
	}
}
