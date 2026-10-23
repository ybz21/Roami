package api

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"
)

type NotificationChoice struct {
	Value string `json:"value"`
	Label string `json:"label"`
}

type notificationPrompt struct {
	Question string
	Choices  []NotificationChoice
	Selected int
	Numbered bool
	YesNo    bool
	Multiple bool
}

var notificationBoxLead = regexp.MustCompile(`^\s*[│┃|╎┆┊╭╰├╞┝─━═]+`)
var notificationMultiHint = regexp.MustCompile(`(?i)(space|空格).{0,24}(toggle|select|check|选择|勾选)|多选|select more than one`)
var notificationCheckbox = regexp.MustCompile(`^\s*\[(?: |x|X|✓)\]\s*`)

func (p notificationPrompt) selectionMode() string {
	if p.Multiple {
		return "multiple"
	}
	return "single"
}

func notificationPromptMode(p notificationPrompt, screen string) notificationPrompt {
	var tail []string
	rows := strings.Split(waitStripCtl(screen), "\n")
	for i := len(rows) - 1; i >= 0 && len(tail) < 12; i-- {
		if line := strings.TrimSpace(rows[i]); line != "" {
			tail = append(tail, line)
		}
	}
	p.Multiple = notificationMultiHint.MatchString(strings.Join(tail, "\n"))
	if p.Multiple {
		for i := range p.Choices {
			p.Choices[i].Label = notificationCheckbox.ReplaceAllString(p.Choices[i].Label, "")
		}
	}
	return p
}

func (p notificationPrompt) token() string {
	b, _ := jsonMarshalPrompt(p)
	return fmt.Sprintf("%x", sha256.Sum256(b))
}

func jsonMarshalPrompt(p notificationPrompt) ([]byte, error) {
	// Cursor motion must not invalidate an otherwise unchanged question.
	return json.Marshal(struct {
		Question        string
		Choices         []NotificationChoice
		Numbered, YesNo bool
		Multiple        bool `json:",omitempty"`
	}{p.Question, p.Choices, p.Numbered, p.YesNo, p.Multiple})
}

func notificationPromptFromScreen(screen string) (notificationPrompt, bool) {
	if q, labels, ok := waitingPrompt(screen); ok && sessionWaiting(screen) {
		p := notificationPrompt{Question: q, Selected: -1, Numbered: true}
		for i, label := range labels {
			p.Choices = append(p.Choices, NotificationChoice{strconv.Itoa(i + 1), label})
		}
		rows := strings.Split(waitStripCtl(screen), "\n")
		var optionRows []int
		for i, line := range rows {
			clean := waitClean(line)
			if waitOpt.MatchString(clean) {
				optionRows = append(optionRows, i)
			}
			if waitCursorPrefix.MatchString(clean) {
				if m := waitOpt.FindStringSubmatch(clean); m != nil {
					n, _ := strconv.Atoi(m[1])
					p.Selected = n - 1
				}
			}
		}
		if len(optionRows) >= len(p.Choices) {
			optionRows = optionRows[len(optionRows)-len(p.Choices):]
			for n, start := range optionRows {
				end := len(rows)
				if n+1 < len(optionRows) {
					end = optionRows[n+1]
				}
				for i := start + 1; i < end; i++ {
					line := waitClean(rows[i])
					if line == "" || waitAction.MatchString(line) {
						break
					}
					if !strings.HasPrefix(rows[i], " ") {
						break
					}
					p.Choices[n].Label += " " + line
				}
			}
		}
		return notificationPromptMode(p, screen), true
	}
	return unnumberedNotificationPrompt(screen)
}

func unnumberedNotificationPrompt(screen string) (notificationPrompt, bool) {
	lines := strings.Split(strings.ReplaceAll(waitStripCtl(screen), "\r", ""), "\n")
	for i, line := range lines {
		lines[i] = waitTail.ReplaceAllString(notificationBoxLead.ReplaceAllString(line, ""), "")
	}
	for i := len(lines) - 1; i >= 0; i-- {
		row := lines[i]
		trimmed := strings.TrimLeft(row, " ")
		if !waitCursorPrefix.MatchString(trimmed) || waitOpt.MatchString(trimmed) {
			continue
		}
		prefix := waitCursorPrefix.FindString(trimmed)
		column := utf8.RuneCountInString(row) - utf8.RuneCountInString(trimmed) + utf8.RuneCountInString(prefix)
		sibling := func(s string) string {
			r := []rune(s)
			if len(r) <= column || strings.TrimSpace(string(r[:column])) != "" || r[column] == ' ' {
				return ""
			}
			label := strings.TrimSpace(string(r[column:]))
			if utf8.RuneCountInString(label) > 160 {
				return ""
			}
			return label
		}
		start, end := i, i
		for start > 0 && i-start < 6 && sibling(lines[start-1]) != "" {
			start--
		}
		for end+1 < len(lines) && end-i < 6 && sibling(lines[end+1]) != "" {
			end++
		}
		if start == end {
			continue
		}
		lo, hi := max(0, start-12), min(len(lines), end+4)
		if !waitAction.MatchString(strings.Join(lines[lo:hi], " ")) {
			continue
		}
		p := notificationPrompt{Selected: i - start}
		for n := start; n <= end; n++ {
			label := sibling(lines[n])
			if n == i {
				label = strings.TrimSpace(strings.TrimPrefix(trimmed, prefix))
			}
			p.Choices = append(p.Choices, NotificationChoice{strconv.Itoa(n - start + 1), label})
		}
		var question []string
		for n := start - 1; n >= max(0, start-20); n-- {
			line := waitClean(lines[n])
			if line == "" && len(question) > 0 {
				if waitQuestion.MatchString(strings.Join(question, " ")) {
					break
				}
				continue
			}
			if line != "" {
				question = append([]string{line}, question...)
			}
		}
		p.Question = strings.Join(question, " ")
		return notificationPromptMode(p, screen), true
	}
	for i := len(lines) - 1; i >= 0; i-- {
		line := waitClean(lines[i])
		if line == "" {
			continue
		}
		if match := waitYesNo.FindStringIndex(line); match != nil {
			return notificationPrompt{Question: strings.TrimSpace(line[:match[1]]), YesNo: true, Selected: -1, Choices: []NotificationChoice{{"yes", ""}, {"no", ""}}}, true
		}
		break
	}
	return notificationPrompt{}, false
}

func (p notificationPrompt) body() string {
	parts := []string{p.Question}
	if !p.YesNo {
		for _, c := range p.Choices {
			parts = append(parts, c.Value+". "+c.Label)
		}
	}
	return strings.Join(parts, "\n")
}
