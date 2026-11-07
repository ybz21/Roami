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
    local words="session swarm chrome adb project agent db server auth plugin help version completion"
    case "${COMP_WORDS[1]}" in
        session)
            words="ls new attach detach kill rename pause resume send keys capture fork children parent swarm env info nw lw kw sp split kp db help"
            case "$prev" in
                attach|detach|kill|rename|pause|resume|send|keys|capture|children)
                    local sessions
                    sessions=$(roami session ls --live --json 2>/dev/null | grep -o '"name":"[^"]*"' | sed 's/"name":"//;s/"$//')
                    COMPREPLY=($(compgen -W "$sessions" -- "$cur"))
                    return ;;
            esac
            case "${COMP_WORDS[2]}" in
                swarm) words="new ls status show members member board work collect chat feed say post plan dependencies control pause resume stop archive help" ;;
                db) words="status migrate backup history restore revive set-home link-agent" ;;
                env) words="set rm clear push" ;;
            esac ;;
        swarm) words="new ls status show members member board work collect chat feed say post plan dependencies control pause resume stop archive help" ;;
        chrome) words="tabs goto click fill text eval screenshot record setup help" ;;
        adb) words="devices shell exec-out push pull install uninstall logcat forward reverse connect disconnect pair version help" ;;
        agent) words="setup init serve status conversations new send history report notify execution" ;;
        project) words="ls show sessions create prefs activity remove" ;;
        db) words="status migrate backup" ;;
        auth) words="login logout status" ;;
    esac
    local swarm_index=0
    if [[ "${COMP_WORDS[1]}" == swarm ]]; then swarm_index=2
    elif [[ "${COMP_WORDS[1]}" == session && "${COMP_WORDS[2]}" == swarm ]]; then swarm_index=3; fi
    if (( swarm_index > 0 && COMP_CWORD > swarm_index )); then
        case "${COMP_WORDS[$swarm_index]}" in
            member)
                if (( COMP_CWORD == swarm_index + 1 )); then words="add ls show"
                else words="--executor --goal --acceptance --key --revision --title --depends-on --integration --file --json --help"; fi ;;
            new|create) words="--key --goal --main-conversation --dir --json --help" ;;
            ls|list) words="--archived --json --help" ;;
            status|board) words="--follow --json --help" ;;
            chat|feed) words="--follow --limit --json --help" ;;
            say) words="--key --to --task-revision --file --json --help" ;;
            post) words="--key --task --run --task-revision --file --json --help" ;;
            dependencies) words="--key --revision --depends-on --clear --file --json --help" ;;
            pause|resume|stop|archive) words="--key --revision --json --help" ;;
            plan|control) words="--file --json --help" ;;
            *) words="--json --help" ;;
        esac
    fi
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
