// Package help renders command help without initializing application resources.
package help

import (
	"fmt"
	"io"
	"os"
	"strings"
	"unicode/utf8"

	ui "github.com/ybz21/Roami/internal/terminalui"
	"golang.org/x/term"
)

type Entry struct{ Name, Description string }
type Section struct {
	Title   string
	Entries []Entry
}
type Page struct {
	Command, Summary string
	Usage            []string
	Sections         []Section
	Examples         []Entry
	Notes            []string
	More             string
}

func IsHelp(s string) bool { return s == "help" || s == "-h" || s == "--help" }

// Request recognizes help only at a command boundary, never inside user input.
func Request(args []string) (topic string, ok bool) {
	if len(args) == 0 {
		return "", true
	}
	if args[0] == "help" {
		return strings.Join(args[1:], " "), true
	}
	if IsHelp(args[len(args)-1]) {
		return strings.Join(args[:len(args)-1], " "), true
	}
	return "", false
}

func (p Page) Render(w io.Writer) error {
	var out strings.Builder
	bold := func(s string) string { return s }
	if f, ok := w.(*os.File); ok && term.IsTerminal(int(f.Fd())) && os.Getenv("TERM") != "dumb" && os.Getenv("NO_COLOR") == "" && os.Getenv("TTMUX_NO_COLOR") == "" && !ui.AgentMode() {
		bold = func(s string) string { return "\x1b[1m" + s + "\x1b[0m" }
	}
	fmt.Fprintf(&out, "%s — %s\n", bold(p.Command), p.Summary)
	fmt.Fprintf(&out, "\n%s\n", bold("用法"))
	for _, line := range p.Usage {
		fmt.Fprintf(&out, "  %s\n", line)
	}
	sections := append([]Section(nil), p.Sections...)
	if len(p.Examples) > 0 {
		sections = append(sections, Section{"示例", p.Examples})
	}
	for _, section := range sections {
		if len(section.Entries) == 0 {
			continue
		}
		fmt.Fprintf(&out, "\n%s\n", bold(section.Title))
		width := 0
		for _, row := range section.Entries {
			if n := utf8.RuneCountInString(row.Name); n <= 28 && n > width {
				width = n
			}
		}
		for _, row := range section.Entries {
			n := utf8.RuneCountInString(row.Name)
			fmt.Fprintf(&out, "  %s", row.Name)
			if row.Description != "" {
				if n > 28 {
					fmt.Fprintf(&out, "\n    %s", row.Description)
				} else {
					fmt.Fprintf(&out, "%s%s", strings.Repeat(" ", width-n+2), row.Description)
				}
			}
			out.WriteByte('\n')
		}
	}
	if len(p.Notes) > 0 {
		fmt.Fprintf(&out, "\n%s\n", bold("说明"))
		for _, note := range p.Notes {
			fmt.Fprintf(&out, "  %s\n", note)
		}
	}
	if p.More != "" {
		fmt.Fprintf(&out, "\n进一步帮助：%s\n", p.More)
	}
	_, err := io.WriteString(w, out.String())
	return err
}
