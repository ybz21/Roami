package okrtemplate

import "embed"

// Files is the same project template shipped by the native OKR Skill.
//
//go:embed okr-development/assets/AGENTS.md okr-development/assets/.roami okr-development/assets/.roami/okr/data/.gitignore
var Files embed.FS
