package api

import (
	"errors"
	"reflect"
	"strings"
	"testing"
)

func TestNotificationPromptUnnumbered(t *testing.T) {
	screen := "Do you trust this folder?\n\n ❯ No, exit\n   Yes, I trust this folder\n\n Enter to confirm · Esc to cancel\n"
	p, ok := notificationPromptFromScreen(screen)
	if !ok || len(p.Choices) != 2 || p.Selected != 0 || p.Numbered || p.Choices[1].Label != "Yes, I trust this folder" {
		t.Fatalf("bad prompt: %+v", p)
	}
	if !sessionWaiting(screen) {
		t.Fatal("unnumbered Codex/Claude menu must trigger attention")
	}
	moved := strings.Replace(screen, " ❯ No, exit\n   Yes", "   No, exit\n ❯ Yes", 1)
	after, _ := notificationPromptFromScreen(moved)
	if p.token() != after.token() {
		t.Fatal("cursor motion changed prompt identity")
	}
}

func TestNotificationPromptBoxedUnnumbered(t *testing.T) {
	screen := "│ Do you trust this folder? │\n│                          │\n│ ❯ No, exit               │\n│   Yes, trust this folder  │\n│ Enter to confirm         │"
	p, ok := notificationPromptFromScreen(screen)
	if !ok || len(p.Choices) != 2 || p.Choices[1].Label != "Yes, trust this folder" {
		t.Fatalf("boxed menu: %+v", p)
	}
}

func TestMultipleNotificationPromptRejectsSingleShortcut(t *testing.T) {
	screen := "Choose platforms\n ❯ [ ] ColorOS 16\n   [x] ColorOS 17\n Enter to confirm · Space to toggle"
	p, ok := notificationPromptFromScreen(screen)
	if !ok || !p.Multiple || p.selectionMode() != "multiple" || len(p.Choices) != 2 || p.Choices[0].Label != "ColorOS 16" {
		t.Fatalf("bad multiple choice: %+v", p)
	}
	after, _ := notificationPromptFromScreen(strings.Replace(screen, "[ ]", "[x]", 1))
	if p.token() != after.token() {
		t.Fatal("checkbox selection changed prompt identity")
	}
	err := respondToNotification(p.token(), "1", func() (string, error) { return screen, nil }, func(...string) error {
		t.Fatal("multiple choice sent an unsafe single shortcut")
		return nil
	})
	if !errors.Is(err, errPromptChanged) {
		t.Fatalf("expected conflict: %v", err)
	}
}

func TestNotificationResponseRejectsStaleQuestion(t *testing.T) {
	p, _ := notificationPromptFromScreen(waitScreen)
	err := respondToNotification(p.token(), "1", func() (string, error) { return strings.Replace(waitScreen, "proceed", "delete", 1), nil }, func(...string) error { t.Fatal("stale request sent input"); return nil })
	if !errors.Is(err, errPromptChanged) {
		t.Fatalf("got %v", err)
	}
}

func TestNotificationResponseYesNoEcho(t *testing.T) {
	screen := "Continue? (y/n) "
	p, _ := notificationPromptFromScreen(screen)
	var sent [][]string
	err := respondToNotification(p.token(), "yes", func() (string, error) { return screen, nil }, func(keys ...string) error {
		sent = append(sent, keys)
		if reflect.DeepEqual(keys, []string{"y"}) {
			screen += "y"
		}
		return nil
	})
	if err != nil || !reflect.DeepEqual(sent, [][]string{{"y"}, {"Enter"}}) {
		t.Fatalf("echoed response: err=%v keys=%v", err, sent)
	}
}

func TestNotificationResponseMovesToExactChoice(t *testing.T) {
	p, _ := notificationPromptFromScreen(waitScreen)
	screen := waitScreen
	var sent [][]string
	err := respondToNotification(p.token(), "2", func() (string, error) { return screen, nil }, func(keys ...string) error {
		sent = append(sent, keys)
		if reflect.DeepEqual(keys, []string{"Down"}) {
			screen = strings.Replace(screen, "❯ 1. Yes\n  2. No", "  1. Yes\n❯ 2. No", 1)
		}
		return nil
	})
	if err != nil || !reflect.DeepEqual(sent, [][]string{{"Down"}, {"Enter"}}) {
		t.Fatalf("err=%v sent=%v", err, sent)
	}
}

func TestNotificationResponseNeverSubmitsNextQuestion(t *testing.T) {
	screen := strings.Replace(waitScreen, "❯ ", "  ", 1)
	p, _ := notificationPromptFromScreen(screen)
	calls := 0
	err := respondToNotification(p.token(), "1", func() (string, error) { return screen, nil }, func(keys ...string) error {
		calls++
		if calls > 1 {
			t.Fatal("sent Enter into the next question")
		}
		screen = strings.Replace(screen, "proceed", "choose a model", 1)
		return nil
	})
	if err != nil || calls != 1 {
		t.Fatalf("err=%v calls=%d", err, calls)
	}
}

func TestWaitingPromptChangesWithoutIdleFrame(t *testing.T) {
	e := newSessionEvents()
	e.observe(inputOf(map[string]string{}, ""))
	sessions := map[string]string{"s": "task"}
	e.observe(inputOf(sessions, waitScreen))
	first := e.observe(inputOf(sessions, waitScreen))
	next := strings.Replace(waitScreen, "proceed", "delete", 1)
	e.observe(inputOf(sessions, next))
	second := e.observe(inputOf(sessions, next))
	if len(first) != 1 || len(second) != 1 || first[0].Prompt == second[0].Prompt {
		t.Fatalf("next confirmation was lost: %+v", second)
	}
}
