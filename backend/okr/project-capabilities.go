package okr

import (
	"errors"
	"io/fs"
	"os"
	"path"
	"strings"
	"unicode/utf8"

	okrtemplate "github.com/ybz21/Roami/skills"
)

type projectMainDefinition struct {
	SchemaVersion    int      `json:"schemaVersion"`
	Role             string   `json:"role"`
	InstructionsFile string   `json:"instructionsFile,omitempty"`
	Skills           []string `json:"skills,omitempty"`
}

func seedGuidance(root *os.Root, name, content string) error {
	if err := mkdir(root, path.Dir(name)); err != nil {
		return err
	}
	f, err := root.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if errors.Is(err, fs.ErrExist) {
		return safeFile(root, name)
	}
	if err != nil {
		return err
	}
	_, err = f.WriteString(content)
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	return closeErr
}

func (s *Store) seedWorkflow(root *os.Root, projectID string) error {
	workflow, err := okrtemplate.Files.ReadFile("okr-development/assets/.roami/okr/AGENTS.md")
	if err != nil {
		return err
	}
	if err := seedGuidance(root, "AGENTS.md", string(workflow)); err != nil {
		return err
	}
	project, err := os.OpenRoot(s.projects()[projectID])
	if err != nil {
		return err
	}
	defer project.Close()
	entry, err := okrtemplate.Files.ReadFile("okr-development/assets/AGENTS.md")
	if err != nil {
		return err
	}
	return seedGuidance(project, "AGENTS.md", string(entry))
}

func seedProjectCapabilities(root *os.Root) error {
	const prefix = "okr-development/assets/.roami/okr/"
	return fs.WalkDir(okrtemplate.Files, strings.TrimSuffix(prefix, "/"), func(name string, item fs.DirEntry, err error) error {
		if err != nil || item.IsDir() {
			return err
		}
		relative := strings.TrimPrefix(name, prefix)
		if relative != "README.md" && relative != "agents/main.md" && relative != "agents/main.json" && relative != "schedules/daily.json" && relative != "data/.gitignore" && !strings.HasPrefix(relative, "manuals/") && !strings.HasPrefix(relative, "skills/") {
			return nil
		}
		body, err := okrtemplate.Files.ReadFile(name)
		if err != nil {
			return err
		}
		return seedGuidance(root, relative, string(body))
	})
}

func projectSkills(root *os.Root, main projectMainDefinition) ([]ProjectSkill, error) {
	if main.SchemaVersion != 1 || main.Role != "main" || main.InstructionsFile != "" && main.InstructionsFile != "main.md" || len(main.Skills) > 16 {
		return nil, ErrInvalid
	}
	result := make([]ProjectSkill, 0, len(main.Skills))
	seen, total := map[string]bool{}, 0
	for _, name := range main.Skills {
		parts := strings.Split(name, "/")
		if len(parts) != 3 || parts[0] != "skills" || !identifier.MatchString(parts[1]) || parts[2] != "SKILL.md" || seen[name] {
			return nil, ErrInvalid
		}
		body, err := readFile(root, name, maxMemory)
		if err != nil {
			return nil, err
		}
		total += len(body)
		if len(body) == 0 || !utf8.Valid(body) || total > maxMemory {
			return nil, ErrInvalid
		}
		seen[name] = true
		result = append(result, ProjectSkill{parts[1], name, string(body), hashText(body)})
	}
	return result, nil
}
