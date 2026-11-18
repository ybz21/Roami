package agentexecution

import (
	"os"
	"path/filepath"
	"strconv"
	"testing"
)

func TestNpmStdioHostKeepsBackgroundCommandsVisible(t *testing.T) {
	for _, scenario := range []string{"host", "shell", "background child", "extra shell child", "untracked launcher", "foreign launcher", "wrong package", "wrong bin", "shell injection", "node arguments", "recycled host", "modified launcher", "path escape"} {
		t.Run(scenario, func(t *testing.T) {
			root := t.TempDir()
			proc := filepath.Join(root, "proc")
			modules := filepath.Join(root, "node_modules")
			pkg := filepath.Join(modules, "@test", "server")
			bin := filepath.Join(modules, ".bin", "test-mcp")
			for _, dir := range []string{pkg, filepath.Dir(bin)} {
				if err := os.MkdirAll(dir, 0700); err != nil {
					t.Fatal(err)
				}
			}
			if err := os.WriteFile(filepath.Join(pkg, "package.json"), []byte(`{"name":"@test/server","bin":{"test-mcp":"server.js"}}`), 0600); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(pkg, "server.js"), []byte("// host"), 0600); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(filepath.Join(pkg, "server.js"), bin); err != nil {
				t.Fatal(err)
			}
			commands := map[int]string{2: "npm exec @test/server@latest\x00", 3: "sh\x00-c\x00test-mcp\x00", 4: "node\x00" + bin + "\x00", 5: "bash\x00-c\x00publish\x00"}
			snapshot := map[int]paneProcess{1: {Parent: 0, Token: "root"}, 2: {Parent: 1, Token: "launcher"}, 3: {Parent: 2, Token: "shell"}, 4: {Parent: 3, Token: "host"}, 5: {Parent: 4, Token: "background"}}
			binding := SessionBinding{PID: 1, Processes: map[int]string{1: "root", 2: "launcher"}}
			pid := 4
			switch scenario {
			case "shell":
				pid = 3
			case "background child":
				pid = 5
			case "extra shell child":
				pid = 3
				snapshot[6] = paneProcess{Parent: 3, Token: "extra"}
			case "untracked launcher":
				delete(binding.Processes, 2)
			case "foreign launcher":
				snapshot[2] = paneProcess{Parent: 9, Token: "launcher"}
			case "wrong package":
				commands[2] = "npm exec @other/server\x00"
			case "wrong bin":
				commands[3] = "sh\x00-c\x00other-mcp\x00"
			case "shell injection":
				commands[3] = "sh\x00-c\x00test-mcp; publish\x00"
			case "node arguments":
				commands[4] += "--eval\x00publish()\x00"
			case "path escape":
				if err := os.WriteFile(filepath.Join(pkg, "package.json"), []byte(`{"name":"@test/server","bin":{"test-mcp":"../../outside.js"}}`), 0600); err != nil {
					t.Fatal(err)
				}
			}
			for id, command := range commands {
				dir := filepath.Join(proc, strconv.Itoa(id))
				if err := os.MkdirAll(dir, 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(dir, "cmdline"), []byte(command), 0600); err != nil {
					t.Fatal(err)
				}
			}
			reads := 0
			read := func(path string) ([]byte, error) {
				if path == filepath.Join(proc, "2", "cmdline") {
					reads++
					if scenario == "modified launcher" && reads > 1 {
						return []byte("npm exec attacker\x00"), nil
					}
				}
				return os.ReadFile(path)
			}
			token := func(id int) string {
				if scenario == "recycled host" && id == 4 {
					return "new"
				}
				return snapshot[id].Token
			}
			got := npmStdioHostAt(proc, binding, snapshot, pid, read, token)
			want := scenario == "host" || scenario == "shell"
			if got != want {
				t.Fatalf("host=%v want=%v", got, want)
			}
		})
	}
}
