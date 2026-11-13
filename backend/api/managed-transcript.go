package api

import (
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"github.com/ybz21/Roami/internal/agentlifecycle"
	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

func managedTranscript(name, executor string) (string, bool) {
	provider, managed, err := agentlifecycle.SessionTranscriptProvider(runtime.New(), name, executor)
	if !managed {
		return "", false
	}
	if err != nil || !codexSessionID.MatchString(provider) {
		return "", true
	}
	home, _ := os.UserHomeDir()
	root, suffix := codexSessionsRoot(), "-"+provider+".jsonl"
	if executor == "claude" {
		root, suffix = filepath.Join(home, ".claude", "projects"), provider+".jsonl"
	} else if executor == "pi" {
		root, suffix = piSessionsRoot(), "_"+provider+".jsonl"
	}
	file := providerTranscriptFile(root, suffix, executor == "claude")
	if executor == "pi" {
		if header, ok := piHeader(file); !ok || header.ID != provider {
			return "", true
		}
	}
	return file, true
}

func providerTranscriptFile(root, suffix string, exact bool) string {
	found := ""
	_ = filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() || !entry.Type().IsRegular() {
			return nil
		}
		matches := strings.HasSuffix(entry.Name(), suffix)
		if exact {
			matches = entry.Name() == suffix
		}
		if !matches {
			return nil
		}
		if found != "" {
			found = ""
			return fs.SkipAll
		}
		found = path
		return nil
	})
	return found
}

func transcriptFileWithin(root, file string) bool {
	relative, err := filepath.Rel(filepath.Clean(root), filepath.Clean(file))
	return err == nil && relative != ".." && !strings.HasPrefix(relative, ".."+string(filepath.Separator)) && !filepath.IsAbs(relative)
}
