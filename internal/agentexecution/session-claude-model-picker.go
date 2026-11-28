package agentexecution

import (
	"context"
	"encoding/json"
	"errors"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/agentproviders"
	"github.com/ybz21/Roami/internal/modelgateway/catalog"
	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

type claudePickerModel struct {
	Display  string `json:"display"`
	NativeID string `json:"nativeId"`
}

var claudePickerRow = regexp.MustCompile(`^\s*(❯\s*)?([0-9]+)\.\s+(.+?)\s+(?:✔\s+)?From gateway\s*$`)
var claudePickerActiveRow = regexp.MustCompile(`^\s*❯\s*([0-9]+)\.\s+`)
var claudePickerMoreBelow = regexp.MustCompile(`^\s*↓\s+[0-9]+\s+more\s*$`)
var claudePickerUnavailable = errors.New("SESSION_MODEL_PICKER_UNCONFIRMED")
var claudePickerNotOpened = errors.New("SESSION_MODEL_PICKER_NOT_OPENED")

func (s Service) claudePickerTarget(ctx context.Context, id string, settings []byte) (claudePickerModel, error) {
	ctx, cancel := context.WithTimeout(ctx, 7*time.Second)
	defer cancel()
	gateway, err := s.claudeFreeGateway(ctx, id)
	var profile struct {
		Environment map[string]string `json:"env"`
	}
	if err != nil || json.Unmarshal(settings, &profile) != nil ||
		strings.TrimRight(profile.Environment["ANTHROPIC_BASE_URL"], "/") != strings.TrimRight(gateway.BaseURL, "/") {
		return claudePickerModel{}, claudePickerUnavailable
	}
	return claudePickerCatalogModel(gateway, id)
}

func claudePickerCatalogModel(gateway claudeGatewayCatalog, id string) (claudePickerModel, error) {
	hidden := catalog.HiddenGatewayMembers(gateway.Models)
	var selected claudePickerModel
	visibleLabels := map[string]int{}
	for _, model := range gateway.Models {
		if !model.IsEnabled() || model.HiddenAtGateway(hidden) {
			continue
		}
		visibleLabels[model.Name]++
		if model.ID != id {
			continue
		}
		wire := model.GatewayAlias
		if wire == "" {
			wire = gateway.QualifiedModelIDs[model.ID]
		}
		if wire == "" {
			wire = model.ID
		}
		selected = claudePickerModel{Display: model.Name, NativeID: agentproviders.ClaudeGatewayModelID(wire)}
	}
	if selected.Display == "" || visibleLabels[selected.Display] != 1 || strings.ContainsAny(selected.Display+selected.NativeID, "\r\n\t`") {
		return claudePickerModel{}, claudePickerUnavailable
	}
	return selected, nil
}

const claudeModelSessionOnlyHint = "s to use this session only · Enter to save · Esc to cancel"

type claudeModelPicker struct {
	selected    int
	destination int
	moreBelow   bool
}

func claudePickerScreen(screen, model string) (claudeModelPicker, bool) {
	lines := strings.Split(screen, "\n")
	start := -1
	var menu claudeModelPicker
	for index, raw := range lines {
		line := strings.TrimSpace(raw)
		if line == "Select model" && index+1 < len(lines) &&
			strings.TrimSpace(lines[index+1]) == "Your pick is the default for new sessions. For other models, use --model." {
			start = index
			menu = claudeModelPicker{}
			continue
		}
		if start < 0 {
			continue
		}
		if line == claudeModelSessionOnlyHint {
			return menu, menu.selected > 0 && strings.TrimSpace(strings.Join(lines[index+1:], "\n")) == ""
		}
		if row := claudePickerActiveRow.FindStringSubmatch(line); row != nil {
			menu.selected, _ = strconv.Atoi(row[1])
		}
		if row := claudePickerRow.FindStringSubmatch(line); row != nil && strings.TrimSpace(row[3]) == model {
			menu.destination, _ = strconv.Atoi(row[2])
		}
		menu.moreBelow = menu.moreBelow || claudePickerMoreBelow.MatchString(line)
	}
	return claudeModelPicker{}, false
}

func claudePickerConfirmation(screen, model string) bool {
	_, tail, ok := strings.Cut(screen, "Switch model?")
	if !ok || strings.Contains(tail, claudeModelSessionOnlyHint) {
		return false
	}
	for _, line := range strings.Split(tail, "\n") {
		line = strings.TrimSpace(line)
		if line == "❯ 1. Yes, switch to "+model {
			return true
		}
	}
	return false
}

func (s Service) operateClaudePicker(ctx context.Context, binding SessionBinding, model claudePickerModel) error {
	ctx, cancel := context.WithTimeout(ctx, 25*time.Second)
	defer cancel()
	s.Runtime.Context = ctx
	entered := false
	err := s.Runtime.WithExclusivePaneInput(binding.Name, binding.Pane, func(scoped runtime.Runtime) error {
		entered = true
		s.Runtime = scoped
		return s.runClaudePicker(ctx, binding, model)
	})
	if !entered {
		return claudePickerNotOpened
	}
	return err
}

func (s Service) runClaudePicker(ctx context.Context, binding SessionBinding, model claudePickerModel) error {
	capture := func() (string, error) {
		return s.Runtime.TmuxOutput("capture-pane", "-p", "-t", binding.Pane)
	}
	safePane := func() bool {
		actual, err := s.paneBinding(binding.ID, false)
		if err != nil || actual.resourceID() != binding.resourceID() ||
			actual.PID != binding.PID || actual.Directory != binding.Directory || !claudeCapabilityProcess(binding) {
			return false
		}
		attached, err := s.Runtime.TmuxOutput("display-message", "-p", "-t", binding.Pane, "#{session_attached}")
		return err == nil && strings.TrimSpace(attached) == "0"
	}
	send := func(keys ...string) error {
		if !safePane() {
			return claudePickerUnavailable
		}
		return s.Runtime.Tmux(append([]string{"send-keys", "-t", binding.Pane}, keys...)...)
	}
	screen, err := capture()
	if err != nil || !claudeEmptyPrompt(screen) || !safePane() {
		return claudePickerNotOpened
	}
	if err = s.Runtime.PasteInput(binding.Pane, "/model"); err != nil {
		return err
	}
	// A second Enter on the chooser saves a profile-wide default.
	if err = send("Enter"); err != nil {
		return err
	}
	selected, direction := 0, "Down"
	confirmationSent, choosing := false, true
	tick := time.NewTicker(100 * time.Millisecond)
	defer tick.Stop()
	for {
		select {
		case <-ctx.Done():
			return claudePickerUnavailable
		case <-tick.C:
		}
		screen, err = capture()
		if err != nil {
			return err
		}
		if !choosing {
			if strings.Contains(screen, "Set model to "+model.Display+" for this session only") && claudeEmptyPrompt(screen) {
				return nil
			}
			if !confirmationSent && claudePickerConfirmation(screen, model.Display) {
				if err = send("Enter"); err != nil {
					return err
				}
				confirmationSent = true
			}
			continue
		}
		menu, ok := claudePickerScreen(screen, model.Display)
		if !ok || menu.selected == selected {
			continue
		}
		selected = menu.selected
		if menu.destination == selected {
			if err = send("s"); err != nil {
				return err
			}
			choosing = false
			continue
		}
		if menu.destination > 0 && menu.destination < selected || menu.destination == 0 && !menu.moreBelow {
			direction = "Up"
		}
		if direction == "Up" && selected == 1 {
			_ = send("Escape")
			return claudePickerUnavailable
		}
		if err = send(direction); err != nil {
			return err
		}
	}
}

func claudeEmptyPrompt(screen string) bool {
	lines := strings.Split(strings.TrimSpace(screen), "\n")
	for index := len(lines) - 1; index > 0; index-- {
		if strings.TrimSpace(lines[index]) == "❯" && index+1 < len(lines) {
			before, after := strings.TrimSpace(lines[index-1]), strings.TrimSpace(lines[index+1])
			return len(before) > 0 && len(after) > 0 && strings.Trim(before, "─") == "" && strings.Trim(after, "─") == ""
		}
	}
	return false
}
