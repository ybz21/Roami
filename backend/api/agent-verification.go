package api

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/internal/agent"
	"github.com/ybz21/Roami/internal/agentinventory"
	"github.com/ybz21/Roami/internal/gitcontext"
)

type agentProof struct {
	Signature string    `json:"signature"`
	At        time.Time `json:"at"`
}
type AgentVerificationStore struct {
	root    string
	mu      sync.Mutex
	running map[string]bool
}

func NewAgentVerificationStore(root string) *AgentVerificationStore {
	return &AgentVerificationStore{root: root, running: map[string]bool{}}
}
func (s *AgentVerificationStore) path(kind string) string {
	return filepath.Join(s.root, "agents", "verified-"+kind+".json")
}
func (a *API) verificationSignature(ctx context.Context, row agentinventory.ProfessionalAgent) (string, error) {
	if !row.Installed {
		return "", fmt.Errorf("AGENT_NOT_INSTALLED")
	}
	info, err := os.Stat(row.Binary)
	if err != nil {
		return "", err
	}
	revision, model := "", ""
	if a.AgentProviders != nil {
		view, e := a.AgentProviders.View(ctx, row.Kind)
		if e != nil {
			return "", e
		}
		revision = view.Revision
		model = view.Current.Model
	}
	// Account and native-config changes invalidate a successful probe without exposing their contents.
	home, _ := os.UserHomeDir()
	configRoot := func(name, fallback string) string {
		if value := os.Getenv(name); value != "" {
			return value
		}
		return fallback
	}
	var paths []string
	switch row.Kind {
	case "claude":
		// .claude.json contains startup counters; settings are covered by the provider revision.
		paths = []string{filepath.Join(configRoot("CLAUDE_CONFIG_DIR", filepath.Join(home, ".claude")), ".credentials.json")}
	case "codex":
		root := configRoot("CODEX_HOME", filepath.Join(home, ".codex"))
		paths = []string{filepath.Join(root, "auth.json"), filepath.Join(root, "config.toml")}
	case "pi":
		paths = []string{filepath.Join(configRoot("PI_CODING_AGENT_DIR", filepath.Join(home, ".pi", "agent")), "auth.json")}
	case "opencode":
		paths = []string{filepath.Join(configRoot("XDG_DATA_HOME", filepath.Join(home, ".local", "share")), "opencode", "auth.json")}
	}
	material := fmt.Sprintf("%s:%s:%d:%d:%s", row.Kind, row.Binary, info.Size(), info.ModTime().UnixNano(), revision)
	if a.AgentVerification != nil {
		data, e := os.ReadFile(filepath.Join(a.AgentVerification.root, "agents", "model-catalog-revision"))
		if e != nil && !os.IsNotExist(e) {
			return "", e
		}
		if e == nil {
			fingerprints := map[string]string{}
			if err := json.Unmarshal(data, &fingerprints); err != nil {
				return "", err
			}
			material += fingerprints[model]
		}
	}
	for _, path := range paths {
		if data, e := os.ReadFile(path); e == nil {
			sum := sha256.Sum256(data)
			material += hex.EncodeToString(sum[:])
		}
	}
	sum := sha256.Sum256([]byte(material))
	return hex.EncodeToString(sum[:]), nil
}
func (a *API) annotateAgentVerification(ctx context.Context, rows []agentinventory.ProfessionalAgent) {
	if a.AgentVerification == nil {
		return
	}
	for i := range rows {
		row := &rows[i]
		if !row.Installed {
			continue
		}
		signature, err := a.verificationSignature(ctx, *row)
		if err != nil {
			continue
		}
		info, err := os.Lstat(a.AgentVerification.path(row.Kind))
		if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > 4096 {
			continue
		}
		data, err := os.ReadFile(a.AgentVerification.path(row.Kind))
		var proof agentProof
		if err == nil && json.Unmarshal(data, &proof) == nil && proof.Signature == signature && time.Since(proof.At) >= 0 && time.Since(proof.At) < 24*time.Hour {
			row.Verified = true
		}
	}
}
func (a *API) VerifyProfessionalAgent(c *gin.Context) {
	kind := c.Param("kind")
	runner := agent.Get(kind)
	if runner == nil {
		c.JSON(400, gin.H{"error": gin.H{"code": "INVALID_AGENT_KIND"}})
		return
	}
	if a.AgentVerification == nil {
		c.JSON(503, gin.H{"error": gin.H{"code": "AGENT_VERIFICATION_UNAVAILABLE"}})
		return
	}
	store := a.AgentVerification
	store.mu.Lock()
	if store.running[kind] {
		store.mu.Unlock()
		c.JSON(409, gin.H{"error": gin.H{"code": "AGENT_VERIFICATION_BUSY"}})
		return
	}
	store.running[kind] = true
	store.mu.Unlock()
	defer func() { store.mu.Lock(); delete(store.running, kind); store.mu.Unlock() }()
	row, err := agentinventory.CheckProfessionalAgent(c.Request.Context(), kind)
	signature, e := a.verificationSignature(c.Request.Context(), row)
	if err != nil || e != nil {
		c.JSON(409, gin.H{"error": gin.H{"code": "AGENT_NOT_INSTALLED"}})
		return
	}
	_ = os.Remove(store.path(kind))
	directory, err := os.MkdirTemp("", "roami-agent-verification-")
	if err != nil {
		c.JSON(500, gin.H{"error": gin.H{"code": "AGENT_VERIFICATION_FAILED"}})
		return
	}
	defer os.RemoveAll(directory)
	ctx, cancel := context.WithTimeout(c.Request.Context(), 60*time.Second)
	defer cancel()
	prompt := "Reply with exactly ROAMI_READY. Do not call tools, read files, or modify anything."
	args := runner.OneShotArgs(agent.StartOpts{MaxTurns: "1"})
	if positional, ok := runner.(interface{ OneShotPromptArg() bool }); ok && positional.OneShotPromptArg() {
		args = append(args, prompt)
	}
	cmd := exec.CommandContext(ctx, row.Binary, args...)
	cmd.Dir = directory
	cmd.Stdin = strings.NewReader(prompt)
	cmd.Env = gitcontext.ForDirectory(os.Environ())
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		if cmd.Process == nil {
			return nil
		}
		return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	cmd.WaitDelay = time.Second
	output := &verificationOutput{}
	cmd.Stdout = output
	cmd.Stderr = io.Discard
	err = cmd.Run()
	if cmd.Process != nil {
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	if err != nil || !verificationResponse(output.text) {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"code": "AGENT_VERIFICATION_FAILED"}})
		return
	}
	after, e := a.verificationSignature(ctx, row)
	if e != nil || after != signature {
		c.JSON(409, gin.H{"error": gin.H{"code": "AGENT_CONFIG_CHANGED"}})
		return
	}
	if err = os.MkdirAll(filepath.Dir(store.path(kind)), 0700); err == nil {
		var file *os.File
		file, err = os.CreateTemp(filepath.Dir(store.path(kind)), ".verified-")
		if err == nil {
			defer os.Remove(file.Name())
			err = json.NewEncoder(file).Encode(agentProof{signature, time.Now().UTC()})
			if err == nil {
				err = file.Sync()
			}
			closeErr := file.Close()
			if err == nil {
				err = closeErr
			}
			if err == nil {
				err = os.Rename(file.Name(), store.path(kind))
			}
		}
	}
	if err != nil {
		c.JSON(500, gin.H{"error": gin.H{"code": "AGENT_VERIFICATION_FAILED"}})
		return
	}
	rows := []agentinventory.ProfessionalAgent{row}
	a.annotateProfessionalPresets(ctx, rows)
	a.annotateAgentVerification(ctx, rows)
	c.JSON(200, gin.H{"agent": rows[0]})
}

type verificationOutput struct{ text string }

func (w *verificationOutput) Write(data []byte) (int, error) {
	n := len(data)
	if len(w.text) < 32768 {
		remaining := 32768 - len(w.text)
		if len(data) > remaining {
			data = data[:remaining]
		}
		w.text += string(data)
	}
	return n, nil
}

func verificationResponse(text string) bool {
	for _, line := range strings.Split(text, "\n") {
		if strings.TrimSpace(line) == "ROAMI_READY" {
			return true
		}
	}
	return false
}
