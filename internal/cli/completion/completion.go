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

const script = `_ttmux_completions() {
    local cur prev cmds
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cmds="ls new fork children parent a attach d detach kill killall rename nw lw kw sp split kp send info source help capture status completion swarm db"

    case "$prev" in
        ttmux)
            COMPREPLY=($(compgen -W "$cmds" -- "$cur"))
            return ;;
        a|attach|kill|rename|send|d|detach|capture|status)
            local sessions
            sessions=$(tmux list-sessions -F '#{session_name}' 2>/dev/null)
            COMPREPLY=($(compgen -W "$sessions" -- "$cur"))
            return ;;
        db)
            COMPREPLY=($(compgen -W "status migrate backup set-home" -- "$cur"))
            return ;;
        swarm)
            COMPREPLY=($(compgen -W "new add ls status activate collect migrate adopt done say listen feed watch board task sql archive rm" -- "$cur"))
            return ;;
        adopt|activate|done|archive|status|collect|say|listen|feed|watch|sql|add|board)
            local swarms
            swarms=$(sqlite3 ~/.roami/meta.db "SELECT name FROM swarms;" 2>/dev/null)
            COMPREPLY=($(compgen -W "$swarms" -- "$cur"))
            return ;;
        sp|split)
            COMPREPLY=($(compgen -W "-h -v" -- "$cur"))
            return ;;
        kw)
            local windows
            windows=$(tmux list-windows -F '#{window_index}' 2>/dev/null)
            COMPREPLY=($(compgen -W "$windows" -- "$cur"))
            return ;;
    esac
}
complete -F _ttmux_completions ttmux
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
	if err := os.WriteFile(filepath.Join(dir, "ttmux"), []byte(script), 0o644); err != nil {
		return err
	}
	bashrc := filepath.Join(home, ".bashrc")
	if !contains(bashrc, "bash_completion.d/ttmux") {
		f, err := os.OpenFile(bashrc, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
		if err != nil {
			return err
		}
		_, _ = f.WriteString("\n# ttmux tab 补全\n[[ -f ~/.bash_completion.d/ttmux ]] && source ~/.bash_completion.d/ttmux\n")
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
