package completion

import (
	"os/exec"
	"strings"
	"testing"
)

func TestSwarmCompletionSupportsBothEntrypoints(t *testing.T) {
	for _, command := range []string{"COMP_WORDS=(roami swarm ''); COMP_CWORD=2", "COMP_WORDS=(roami session swarm ''); COMP_CWORD=3"} {
		script := Script + "\n" + command + "; _roami_complete; printf '%s\\n' \"${COMPREPLY[@]}\""
		output, err := exec.Command("bash", "-c", script).CombinedOutput()
		if err != nil {
			t.Fatal(err, string(output))
		}
		words := strings.Fields(string(output))
		has := func(word string) bool {
			for _, item := range words {
				if item == word {
					return true
				}
			}
			return false
		}
		for _, word := range []string{"chat", "member", "pause", "resume", "stop", "collect", "help"} {
			if !has(word) {
				t.Errorf("missing %s: %s", word, output)
			}
		}
		for _, word := range []string{"adopt", "done", "activate", "task", "sql", "watch", "listen"} {
			if has(word) {
				t.Errorf("removed command offered: %s", word)
			}
		}
	}
	for _, command := range []string{"COMP_WORDS=(roami swarm member ''); COMP_CWORD=3", "COMP_WORDS=(roami session swarm member ''); COMP_CWORD=4"} {
		output, err := exec.Command("bash", "-c", Script+"\n"+command+"; _roami_complete; printf '%s\\n' \"${COMPREPLY[@]}\"").CombinedOutput()
		if err != nil || !strings.Contains(string(output), "add") {
			t.Fatal(err, string(output))
		}
	}
}
