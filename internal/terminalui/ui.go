// Package ui centralizes terminal styling and the message/prompt helpers that
// the shell CLI implemented in lib/core.sh (msg_ok/msg_err/_confirm/_pick_session).
// Colors are emitted only when stdout is a real terminal and NO_COLOR is unset,
// so piped/JSON consumers and tests get clean output.
package ui

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"strings"
)

// Palette holds the ANSI escapes; they are empty when color is disabled.
type Palette struct {
	Bold, Dim, Cyan, Green, Yellow, Red, Blue, Magenta, Reset string
}

var (
	agentMode = os.Getenv("TTMUX_AGENT") != "" || os.Getenv("TTMUX_QUIET") != ""
	colored   = supportsColor()
)

// SetAgentMode toggles machine-friendly output at runtime (the -q/--quiet flag).
// In agent mode colors are off and status/error messages go to stderr so stdout
// carries only structured data.
func SetAgentMode(on bool) {
	agentMode = on
	colored = supportsColor()
}

// AgentMode reports whether machine-friendly output is active.
func AgentMode() bool { return agentMode }

func supportsColor() bool {
	if agentMode {
		return false
	}
	if os.Getenv("NO_COLOR") != "" || os.Getenv("TTMUX_NO_COLOR") != "" {
		return false
	}
	info, err := os.Stdout.Stat()
	return err == nil && info.Mode()&os.ModeCharDevice != 0
}

// P returns the active palette (escapes or empty strings).
func P() Palette {
	if !colored {
		return Palette{}
	}
	return Palette{
		Bold: "\033[1m", Dim: "\033[2m", Cyan: "\033[36m", Green: "\033[32m",
		Yellow: "\033[33m", Red: "\033[31m", Blue: "\033[34m", Magenta: "\033[35m",
		Reset: "\033[0m",
	}
}

// Icons used across the CLI, mirroring lib/core.sh.
const (
	IconSession = "▸"
	// IconSessionDormant 休眠会话：台账里还认得它，attach 一下就回来。
	// 空心与 IconSession 的实心相对，一眼分得出「在」和「活」。
	IconSessionDormant = "▹"
	IconWindow         = "◻"
	IconOK             = "✔"
	IconErr            = "✘"
	IconInfo           = "●"
	IconWarn           = "⚠"
	IconRun            = "⟳"
	IconDone           = "■"
	IconGroup          = "◆"
)

// msgTarget routes status/info/warn messages: stderr in agent mode (keeping
// stdout for data), otherwise the caller's writer.
func msgTarget(w io.Writer) io.Writer {
	if agentMode {
		return os.Stderr
	}
	return w
}

func Ok(w io.Writer, format string, a ...any) {
	p := P()
	fmt.Fprintf(msgTarget(w), " %s%s%s %s\n", p.Green, IconOK, p.Reset, fmt.Sprintf(format, a...))
}
func Info(w io.Writer, format string, a ...any) {
	p := P()
	fmt.Fprintf(msgTarget(w), " %s%s%s %s\n", p.Blue, IconInfo, p.Reset, fmt.Sprintf(format, a...))
}
func Warn(w io.Writer, format string, a ...any) {
	p := P()
	fmt.Fprintf(msgTarget(w), " %s%s%s %s\n", p.Yellow, IconWarn, p.Reset, fmt.Sprintf(format, a...))
}

// Err always writes to stderr (mirrors the shell's msg_err >&2).
func Err(_ io.Writer, format string, a ...any) {
	p := P()
	fmt.Fprintf(os.Stderr, " %s%s%s %s\n", p.Red, IconErr, p.Reset, fmt.Sprintf(format, a...))
}

// Bold wraps s in bold (or returns it unchanged when color is disabled).
func Bold(s string) string { p := P(); return p.Bold + s + p.Reset }

// Dim wraps s in the dim style.
func Dim(s string) string { p := P(); return p.Dim + s + p.Reset }

// Confirm prints a yes/no prompt to /dev/tty and reads the answer, mirroring
// _confirm. It returns false when no terminal is available.
func Confirm(prompt string) bool {
	tty, err := os.OpenFile("/dev/tty", os.O_RDWR, 0)
	if err != nil {
		return false
	}
	defer tty.Close()
	fmt.Fprintf(tty, "   %s [y/N] ", prompt)
	line, _ := bufio.NewReader(tty).ReadString('\n')
	line = strings.TrimSpace(line)
	return line == "y" || line == "Y"
}

// ReadLine prompts on /dev/tty and returns the trimmed response.
func ReadLine(prompt string) (string, bool) {
	tty, err := os.OpenFile("/dev/tty", os.O_RDWR, 0)
	if err != nil {
		return "", false
	}
	defer tty.Close()
	fmt.Fprint(tty, prompt)
	line, err := bufio.NewReader(tty).ReadString('\n')
	if err != nil && line == "" {
		return "", false
	}
	return strings.TrimSpace(line), true
}
