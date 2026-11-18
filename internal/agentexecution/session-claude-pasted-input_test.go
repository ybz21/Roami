package agentexecution

import "testing"

func TestClaudePastedInputPreservesExactHostPrompt(t *testing.T) {
	raw := "Owned task\nRead only the project files."
	expected := workspaceHash(raw)
	wrapped := "\n\n<pasted_content id=\"84f2\">\n" + raw + "\n</pasted_content id=\"84f2\">\n"
	if claudeInputHash(raw, expected) != expected || claudeInputHash(wrapped, expected) != expected {
		t.Fatal("owned input lost its identity")
	}
	for _, input := range []string{"extra" + wrapped, wrapped + "extra", "\n\n<pasted_content id=\"other\">\n" + raw + "\n</pasted_content id=\"84f2\">\n", "\n\n<pasted_content id=\"84f2\">\n" + raw + "\nextra\n</pasted_content id=\"84f2\">\n"} {
		if claudeInputHash(input, expected) == expected {
			t.Fatal("changed input accepted")
		}
	}
}
