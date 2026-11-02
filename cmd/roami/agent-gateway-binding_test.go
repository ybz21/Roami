package main

import (
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"testing"

	"github.com/ybz21/Roami/internal/agentruntime"
	"github.com/ybz21/Roami/internal/modelgateway"
	metadb "github.com/ybz21/Roami/internal/storage"
)

func gatewayBindingOutput(t *testing.T, args ...string) (int, string) {
	t.Helper()
	output, err := os.CreateTemp(t.TempDir(), "binding")
	if err != nil {
		t.Fatal(err)
	}
	oldOut, oldErr := os.Stdout, os.Stderr
	os.Stdout, os.Stderr = output, output
	defer func() { os.Stdout, os.Stderr = oldOut, oldErr; output.Close() }()
	code := runAgentGateway(args)
	raw, err := os.ReadFile(output.Name())
	if err != nil {
		t.Fatal(err)
	}
	return code, string(raw)
}

func gatewayBindingNode(t *testing.T) agentruntime.Paths {
	t.Helper()
	root := t.TempDir()
	paths, err := metadb.ResolvePaths(root, root)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := paths.Ensure(); err != nil {
		t.Fatal(err)
	}
	node, err := agentruntime.Resolve(root, root)
	if err != nil {
		t.Fatal(err)
	}
	socket := modelgateway.Socket(node.Socket)
	if err := os.MkdirAll(filepath.Dir(socket), 0700); err != nil {
		t.Fatal(err)
	}
	return node
}

func TestGatewayBindingUsesSelectedNodeWithoutInheritedInstanceOverrides(t *testing.T) {
	first, second := gatewayBindingNode(t), gatewayBindingNode(t)
	t.Setenv("ROAMI_HOME", first.Storage.Home)
	t.Setenv("ROAMI_DATA", first.Storage.Data)
	t.Setenv("ROAMI_DATABASE_DIR", first.Storage.Database)
	for _, node := range []agentruntime.Paths{first, second} {
		socket := modelgateway.Socket(node.Socket)
		listener, err := net.Listen("unix", socket)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { listener.Close() })
		if err = os.Chmod(socket, 0600); err != nil {
			t.Fatal(err)
		}
		code, raw := gatewayBindingOutput(t, "binding", "--data-root", node.Storage.Data)
		var binding struct {
			Data map[string]string `json:"data"`
		}
		if code != 0 || json.Unmarshal([]byte(raw), &binding) != nil {
			t.Fatalf("%d %s", code, raw)
		}
		if len(binding.Data) != 2 || binding.Data["socket"] != socket || binding.Data["instanceId"] != node.InstanceID {
			t.Fatalf("%+v", binding.Data)
		}
	}
}

func TestGatewayBindingRejectsMissingNonSocketAndPublicSocket(t *testing.T) {
	for _, kind := range []string{"missing", "file", "symlink", "public"} {
		t.Run(kind, func(t *testing.T) {
			node := gatewayBindingNode(t)
			socket := modelgateway.Socket(node.Socket)
			switch kind {
			case "file":
				if err := os.WriteFile(socket, []byte("fixture"), 0600); err != nil {
					t.Fatal(err)
				}
			case "symlink":
				if err := os.Symlink("not-a-gateway", socket); err != nil {
					t.Fatal(err)
				}
			case "public":
				listener, err := net.Listen("unix", socket)
				if err != nil {
					t.Fatal(err)
				}
				defer listener.Close()
				if err = os.Chmod(socket, 0666); err != nil {
					t.Fatal(err)
				}
			}
			code, raw := gatewayBindingOutput(t, "binding", "--data-root", node.Storage.Data)
			if code != 1 || raw != "MODEL_GATEWAY_UNAVAILABLE\n" {
				t.Fatalf("%d %s", code, raw)
			}
		})
	}
}
