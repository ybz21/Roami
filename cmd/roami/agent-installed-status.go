package main

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/ybz21/Roami/backend/config"
	"github.com/ybz21/Roami/internal/agentruntime"
)

func agentInstalledStatus() error {
	paths, err := agentruntime.Resolve("", "")
	if err != nil {
		return err
	}
	data, err := agentRequest(paths.Socket, "GET", "/v1/status", nil)
	if err != nil {
		return err
	}
	var status struct {
		Data struct {
			Managed bool   `json:"managed"`
			Version string `json:"version"`
		} `json:"data"`
	}
	if err := json.Unmarshal(data, &status); err != nil {
		return err
	}
	if !status.Data.Managed || status.Data.Version != version {
		return fmt.Errorf("AGENT_RELEASE_NOT_READY")
	}
	if _, err := agentRequest(paths.Socket, "GET", "/v1/model-settings", nil); err != nil {
		return err
	}
	cfg, err := config.Load(config.ResolvePath())
	if err != nil {
		return err
	}
	host, port, err := net.SplitHostPort(cfg.Web.Bind)
	if err != nil {
		return err
	}
	if host == "" || host == "0.0.0.0" {
		host = "127.0.0.1"
	}
	if host == "::" {
		host = "::1"
	}
	scheme := "http"
	roots, _ := x509.SystemCertPool()
	if roots == nil {
		roots = x509.NewCertPool()
	}
	if raw, err := os.ReadFile(filepath.Join(paths.Storage.Data, "tls", "ca-cert.pem")); err == nil {
		roots.AppendCertsFromPEM(raw)
	}
	if cfg.Web.TLS {
		scheme = "https"
	}
	transport := &http.Transport{TLSClientConfig: &tls.Config{RootCAs: roots, MinVersion: tls.VersionTLS12}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 2 * time.Second}
	response, err := client.Get(scheme + "://" + net.JoinHostPort(host, port) + "/api/version")
	if err != nil {
		return err
	}
	defer response.Body.Close()
	var web struct {
		Data struct {
			Version string `json:"version"`
		} `json:"data"`
	}
	if response.StatusCode != 200 {
		return fmt.Errorf("WEB_RELEASE_NOT_READY")
	}
	if err := json.NewDecoder(response.Body).Decode(&web); err != nil {
		return err
	}
	if web.Data.Version != version {
		return fmt.Errorf("WEB_RELEASE_MISMATCH")
	}
	return nil
}
