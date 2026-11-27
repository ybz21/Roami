package main

import (
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/ybz21/Roami/internal/agentruntime"
	"github.com/ybz21/Roami/internal/filelock"
	"github.com/ybz21/Roami/internal/modelgateway/httpapi"
	metadb "github.com/ybz21/Roami/internal/storage"
)

func runAgentUpgrade(args []string) int {
	if len(args) != 1 {
		return 2
	}
	paths, err := agentruntime.Resolve("", "")
	if err != nil {
		p, pathErr := metadb.ResolvePaths("", "")
		if pathErr == nil && os.IsNotExist(err) {
			if _, lockErr := os.Stat(filepath.Join(p.Data, "locks", "agent-runtime.lock")); os.IsNotExist(lockErr) {
				return 0
			}
		}
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if !agentReady(paths.Socket) {
		// An unreachable but locked writer is unknown, never safe to replace.
		lock, err := os.OpenFile(filepath.Join(paths.Storage.Data, "locks", "agent-runtime.lock"), os.O_RDWR, 0)
		if os.IsNotExist(err) {
			return 0
		}
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		defer lock.Close()
		unlock, err := filelock.Lock(lock, false, true)
		if err != nil {
			fmt.Fprintln(os.Stderr, "AGENT_UPGRADE_RUNTIME_UNKNOWN")
			return 1
		}
		defer func() { _ = unlock() }()
		return 0
	}
	raw, err := agentRequest(paths.Socket, "GET", "/v1/status", nil)
	var status struct {
		Data struct {
			Managed bool `json:"managed"`
		} `json:"data"`
	}
	if err != nil || json.Unmarshal(raw, &status) != nil || !status.Data.Managed {
		fmt.Fprintln(os.Stderr, "AGENT_UPGRADE_UNMANAGED_RUNTIME: stop the manually started runtime first")
		return 1
	}
	err = prepareAgentUpgrade(paths.Socket, args[0] == "resume-upgrade")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}

func setAgentUpgrade(socket string, resume bool) error {
	_, err := agentRequest(socket, "POST", "/internal/installation/quiesce", map[string]bool{"resume": resume})
	return err
}

func prepareAgentUpgrade(agentSocket string, resume bool) error {
	gatewaySocket := httpapi.Socket(agentSocket)
	if resume {
		_, gatewayErr := changeGatewayUpgrade(gatewaySocket, "resume", "")
		return errors.Join(gatewayErr, setAgentUpgrade(agentSocket, true))
	}

	deadline := time.Now().Add(time.Minute)
	lease := rand.Text()
	state, err := changeGatewayUpgrade(gatewaySocket, "begin", lease)
	if err != nil {
		return err
	}
	if state == nil {
		return setAgentUpgrade(agentSocket, false)
	}
	ready := false
	defer func() {
		if !ready {
			_, _ = changeGatewayUpgrade(gatewaySocket, "resume", lease)
			_ = setAgentUpgrade(agentSocket, true)
		}
	}()
	if err := setAgentUpgrade(agentSocket, false); err != nil {
		return err
	}

	for {
		state, err = changeGatewayUpgrade(gatewaySocket, "status", lease)
		if err != nil {
			return err
		}
		if state == nil || time.Now().After(deadline) {
			return errors.New("MODEL_GATEWAY_UPGRADE_NOT_READY")
		}
		if state.Active == 0 {
			ready = true
			return nil
		}
		time.Sleep(250 * time.Millisecond)
	}
}

func changeGatewayUpgrade(socket, action, lease string) (*httpapi.UpgradeState, error) {
	raw, err := agentRequest(socket, "POST", httpapi.UpgradePath, httpapi.UpgradeRequest{Action: action, Lease: lease})
	var response struct {
		Data struct {
			Active *int `json:"active"`
		} `json:"data"`
		Error struct {
			Code string `json:"code"`
		} `json:"error"`
	}
	parseErr := json.Unmarshal(raw, &response)
	if err != nil {
		if response.Error.Code == "MODEL_GATEWAY_ROUTE_NOT_FOUND" && action != "status" {
			return nil, nil
		}
		if response.Error.Code != "" {
			return nil, errors.New(response.Error.Code)
		}
		return nil, fmt.Errorf("MODEL_GATEWAY_UPGRADE_UNAVAILABLE: %w", err)
	}
	if parseErr != nil || response.Data.Active == nil || *response.Data.Active < 0 {
		return nil, errors.New("MODEL_GATEWAY_UPGRADE_INVALID_RECEIPT")
	}
	return &httpapi.UpgradeState{Active: *response.Data.Active}, nil
}
