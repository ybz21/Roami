package agentlifecycle

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/pelletier/go-toml/v2"
)

func TestMain(m *testing.M) {
	if os.Getenv("ROAMI_LIFECYCLE_FIXTURE") == "1" {
		switch os.Args[1] {
		case "--help":
			fmt.Println("Codex fixture --no-daemon --settings")
		case "app-server":
			decoder, encoder := json.NewDecoder(os.Stdin), json.NewEncoder(os.Stdout)
			for {
				var request struct {
					ID     *int   `json:"id"`
					Method string `json:"method"`
				}
				if decoder.Decode(&request) != nil {
					break
				}
				if request.ID == nil {
					continue
				}
				result := json.RawMessage(`{}`)
				if request.Method == "config/read" {
					result = json.RawMessage(`{"config":` + os.Getenv("ROAMI_LIFECYCLE_CONFIG") + `}`)
				}
				_ = encoder.Encode(map[string]any{"id": request.ID, "result": result})
			}
		case "notifier":
			data, _ := json.Marshal(os.Args[2:])
			_ = os.WriteFile(os.Getenv("ROAMI_NOTIFIER_RECEIPT"), data, 0600)
		default:
			os.Exit(1)
		}
		os.Exit(0)
	}
	os.Exit(m.Run())
}

func fixtureOptions(t *testing.T, configuration any) SessionOptions {
	t.Helper()
	data, err := json.Marshal(configuration)
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("ROAMI_LIFECYCLE_FIXTURE", "1")
	t.Setenv("ROAMI_LIFECYCLE_CONFIG", string(data))
	binary, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	return SessionOptions{Binary: binary, Executable: filepath.Join(t.TempDir(), "roami 'callback' $()"), Directory: t.TempDir(), DataDir: t.TempDir()}
}

func TestScopedArgumentsAreValidTOMLAndRetainHookTrust(t *testing.T) {
	options := fixtureOptions(t, map[string]any{"notify": nil})
	args, err := PrepareCodex(context.Background(), options)
	if err != nil {
		t.Fatal(err)
	}
	if args[0] != "--no-daemon" || strings.Contains(strings.Join(args, " "), "bypass") {
		t.Fatal("callbacks must use the local server without bypassing trust")
	}
	values := map[string]any{}
	for index := 1; index < len(args); index += 2 {
		if args[index] != "-c" {
			t.Fatal("configuration overrides are separate argv entries")
		}
		var value map[string]any
		if err := toml.Unmarshal([]byte(args[index+1]), &value); err != nil {
			t.Fatal(err)
		}
		for key, item := range value {
			if key == "hooks" {
				if values[key] == nil {
					values[key] = map[string]any{}
				}
				for event, groups := range item.(map[string]any) {
					values[key].(map[string]any)[event] = groups
				}
			} else {
				values[key] = item
			}
		}
	}
	hooks := values["hooks"].(map[string]any)
	if len(hooks) != 7 {
		t.Fatal("missing lifecycle groups")
	}
	interrupt := hooks["Interrupt"].([]any)[0].(map[string]any)["hooks"].([]any)[0].(map[string]any)
	if interrupt["timeout"] != int64(3) || !strings.Contains(interrupt["command"].(string), "'agent' 'execution' 'event'") {
		t.Fatal("unsupported interruption hook contract")
	}
	if len(values["notify"].([]any)) != 9 {
		t.Fatal("the vendor JSON argument must follow --notification")
	}
}

func TestEffectiveNotifierIsPreservedAsPrivateImmutableArgv(t *testing.T) {
	binary, _ := os.Executable()
	original := []string{binary, "notifier", "literal $(do-not-run)", "中文参数"}
	options := fixtureOptions(t, map[string]any{"notify": original})
	args, err := PrepareCodex(context.Background(), options)
	if err != nil {
		t.Fatal(err)
	}
	var value struct {
		Notify []string `toml:"notify"`
	}
	if err := toml.Unmarshal([]byte(args[len(args)-1]), &value); err != nil {
		t.Fatal(err)
	}
	if value.Notify[5] != "notify" || value.Notify[8] != "--chain" {
		t.Fatal("existing notification handler was replaced")
	}
	path := value.Notify[9]
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatal("notifier argv must be private")
	}
	directory, _ := os.Stat(filepath.Dir(path))
	if directory.Mode().Perm() != 0700 {
		t.Fatal("notifier directory must be private")
	}
	receipt := filepath.Join(t.TempDir(), "receipt.json")
	t.Setenv("ROAMI_NOTIFIER_RECEIPT", receipt)
	notification := `{"type":"agent-turn-complete","last-assistant-message":"fixture"}`
	if err := ForwardNotification(context.Background(), options.DataDir, path, notification, &bytes.Buffer{}, &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
	data, _ := os.ReadFile(receipt)
	var received []string
	if json.Unmarshal(data, &received) != nil || !reflect.DeepEqual(received, append(original[2:], notification)) {
		t.Fatal("notifier arguments were changed or shell-interpreted")
	}
	again, err := storeNotifier(options.DataDir, original)
	if err != nil || again != path {
		t.Fatal("same notifier should reuse its immutable configuration")
	}
	if err := os.WriteFile(path, []byte(`[]`), 0600); err != nil {
		t.Fatal(err)
	}
	if err := ForwardNotification(context.Background(), options.DataDir, path, notification, &bytes.Buffer{}, &bytes.Buffer{}); err == nil {
		t.Fatal("changed notifier contents were executed")
	}
}

func TestDisabledOrManagedOnlyHooksAreNeverOverridden(t *testing.T) {
	for _, config := range []map[string]any{{"features": map[string]any{"hooks": false}}, {"allow_managed_hooks_only": true}} {
		t.Run(fmt.Sprint(config), func(t *testing.T) {
			options := fixtureOptions(t, config)
			if args, err := PrepareCodex(context.Background(), options); err == nil || len(args) != 0 {
				t.Fatal("disabled hooks must remain disabled")
			}
		})
	}
}

func TestCancelledConfigurationProbeCannotLaunchOrLeaveACommand(t *testing.T) {
	options := fixtureOptions(t, map[string]any{})
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if args, err := PrepareCodex(ctx, options); err == nil || len(args) != 0 {
		t.Fatal("cancelled preparation returned a launch command")
	}
}

func TestInstalledCodexReadOnlyConfigurationContract(t *testing.T) {
	if os.Getenv("ROAMI_TEST_INSTALLED_CODEX") != "1" {
		t.Skip("explicit opt-in for installed Codex configuration inspection")
	}
	binary, err := exec.LookPath("codex")
	if err != nil {
		t.Fatal(err)
	}
	executable, _ := os.Executable()
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	args, err := PrepareCodex(ctx, SessionOptions{Binary: binary, Executable: executable, Directory: t.TempDir(), DataDir: t.TempDir()})
	if err != nil || len(args) == 0 || args[0] != "--no-daemon" {
		t.Fatalf("installed read-only configuration contract failed: %v", err)
	}
	effective, err := readCodexConfiguration(ctx, binary, t.TempDir(), args[1:]...)
	if err != nil || len(effective.Notify) < 9 || effective.Notify[len(effective.Notify)-1] != "--notification" {
		t.Fatalf("installed CLI rejected scoped configuration: %v", err)
	}

}
