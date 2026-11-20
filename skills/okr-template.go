package okrtemplate

import "embed"

// Files is the same project template shipped by the native OKR Skill.
//
//go:embed okr-development/assets/AGENTS.md okr-development/assets/.roami okr-development/assets/.roami/okr/data/.gitignore
//go:embed okr-development/assets/workspaces/README.md okr-development/assets/materials/README.md
var Files embed.FS
