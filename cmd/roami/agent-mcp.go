package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/ybz21/Roami/internal/agentruntime"
)

func runAgentMCP(args []string) int {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" {
		fmt.Println("roami agent mcp install|serve|status [--runtime-dir PATH]\nIndependent MCP owner; configure ROAMI_MCP_SOCKET in the Agent environment.")
		return 0
	}
	sub := args[0]
	fs := flag.NewFlagSet("agent mcp "+sub, flag.ContinueOnError)
	dirFlag := fs.String("runtime-dir", "", "Python runtime project")
	homeFlag := fs.String("home-root", "", "Explicit instance home")
	dataFlag := fs.String("data-root", "", "Explicit instance data root")
	socketFlag := fs.String("socket", "", "Explicit private MCP socket")
	if err := fs.Parse(args[1:]); err != nil || fs.NArg() != 0 {
		return 2
	}
	paths, err := agentruntime.Resolve(*homeFlag, *dataFlag)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	socketPath := mcpSocketPath(paths)
	if *socketFlag != "" {
		socketPath = *socketFlag
	}
	if sub == "status" {
		transport := agentruntime.Transport(socketPath)
		defer transport.CloseIdleConnections()
		response, e := (&http.Client{Transport: transport, Timeout: 3 * time.Second}).Get("http://roami-mcp/v1/state")
		if e != nil {
			fmt.Fprintln(os.Stderr, "MCP_DAEMON_UNAVAILABLE")
			return 1
		}
		defer response.Body.Close()
		if response.StatusCode != 200 {
			fmt.Fprintln(os.Stderr, "MCP_DAEMON_UNAVAILABLE")
			return 1
		}
		var value any
		if e = json.NewDecoder(response.Body).Decode(&value); e != nil {
			fmt.Fprintln(os.Stderr, "MCP_DAEMON_INVALID_RESPONSE")
			return 1
		}
		_ = json.NewEncoder(os.Stdout).Encode(value)
		return 0
	}
	if sub != "serve" && sub != "install" {
		fmt.Fprintln(os.Stderr, "unknown MCP command")
		return 2
	}
	dir, err := agentRuntimeDir(*dirFlag)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if sub == "install" {
		if err = installMCPService(dir, paths, socketPath); err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		return 0
	}
	cmd, err := agentPythonCommand(dir, paths, false)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	cmd.Args = []string{cmd.Path, "-m", "roami_agent.server.mcp_daemon", "--data-root", paths.Storage.Data, "--config", paths.Config, "--socket", socketPath}
	if err = cmd.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "MCP_DAEMON_EXITED")
		return 1
	}
	return 0
}

func mcpDaemonReady(socketPath string, dataRoot string) bool {
	transport := agentruntime.Transport(socketPath)
	defer transport.CloseIdleConnections()
	response, err := (&http.Client{Transport: transport, Timeout: time.Second}).Get("http://roami-mcp/v1/state")
	if err != nil {
		return false
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return false
	}
	var value struct {
		DataRoot string `json:"dataRoot"`
	}
	return json.NewDecoder(response.Body).Decode(&value) == nil && filepath.Clean(value.DataRoot) == filepath.Clean(dataRoot)
}
