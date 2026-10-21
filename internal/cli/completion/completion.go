// Package completion installs the bash tab-completion script (mirrors
// _install_completion). The completion script itself is shell that runs in the
// user's interactive shell, independent of the ttmux implementation language.
package completion

import (
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/ybz21/Roami/internal/terminalui"
)

// Script completes only the public Roami command vocabulary.
const Script = `_roami_complete() {
    local cur="${COMP_WORDS[COMP_CWORD]}" prev="${COMP_WORDS[COMP_CWORD-1]}"
    local words="session chrome project agent db server auth plugin help version completion"
    case "${COMP_WORDS[1]}" in
        session)
            words="ls new attach detach kill rename send keys capture fork children parent swarm env info nw lw kw sp split kp db help"
            case "$prev" in
                attach|detach|kill|rename|send|keys|capture|children)
                    local sessions
                    sessions=$(roami session ls --live --json 2>/dev/null | grep -o '"name":"[^"]*"' | sed 's/"name":"//;s/"$//')
                    COMPREPLY=($(compgen -W "$sessions" -- "$cur"))
                    return ;;
            esac
            case "${COMP_WORDS[2]}" in
                swarm) words="new add ls status activate done say feed listen watch board task adopt archive rm sql" ;;
                db) words="status migrate backup history restore revive set-home link-agent" ;;
                env) words="set rm clear push" ;;
            esac ;;
        chrome) words="tabs goto click fill text eval screenshot record setup help" ;;
        agent) words="setup init serve status conversations new send history report notify execution" ;;
        project) words="ls show sessions create prefs activity remove" ;;
        db) words="status migrate backup" ;;
        auth) words="login logout status" ;;
    esac
    COMPREPLY=($(compgen -W "$words" -- "$cur"))
}
complete -F _roami_complete roami
`

// Install writes the completion script and wires it into ~/.bashrc.
func Install(w io.Writer) error {
	home, err := os.UserHomeDir()
	if err != nil {
		return err
	}
	dir := filepath.Join(home, ".bash_completion.d")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(dir, "roami"), []byte(Script), 0o644); err != nil {
		return err
	}
	bashrc := filepath.Join(home, ".bashrc")
	data, err := os.ReadFile(bashrc)
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	var lines []string
	for _, line := range strings.Split(string(data), "\n") {
		if strings.TrimSpace(line) == "# ttmux tab 补全" || strings.TrimSpace(line) == "[[ -f ~/.bash_completion.d/ttmux ]] && source ~/.bash_completion.d/ttmux" {
			continue
		}
		lines = append(lines, line)
	}
	if cleaned := strings.Join(lines, "\n"); cleaned != string(data) {
		if err := os.WriteFile(bashrc, []byte(cleaned), 0600); err != nil {
			return err
		}
	}
	if !contains(bashrc, "bash_completion.d/roami") {
		f, err := os.OpenFile(bashrc, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
		if err != nil {
			return err
		}
		_, _ = f.WriteString("\n# Roami tab 补全\n[[ -f ~/.bash_completion.d/roami ]] && source ~/.bash_completion.d/roami\n")
		_ = f.Close()
	}
	ui.Ok(w, "Tab 补全已安装")
	ui.Info(w, "运行 source ~/.bashrc 或重开终端生效")
	return nil
}

func contains(path, needle string) bool {
	b, err := os.ReadFile(path)
	return err == nil && strings.Contains(string(b), needle)
}
