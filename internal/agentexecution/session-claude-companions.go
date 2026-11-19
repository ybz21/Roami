package agentexecution

import (
	"encoding/json"
	"path/filepath"
	"regexp"
	"strings"
)

type claudeInlineSkill struct {
	name     string
	prompt   string
	returned bool
	expanded bool
}

type claudeCompanions struct {
	binding SessionBinding
	prompt  string
	tools   map[string]string
	skills  map[string]*claudeInlineSkill
	images  map[string]string
}

func newClaudeCompanions(binding SessionBinding) *claudeCompanions {
	return &claudeCompanions{binding: binding, tools: map[string]string{}, skills: map[string]*claudeInlineSkill{}, images: map[string]string{}}
}

func (c *claudeCompanions) call(block claudeInterruptedBlock) bool {
	if block.Type != "tool_use" {
		return true
	}
	if block.Name != "Skill" {
		if !synchronousClaudeTool(block) {
			return false
		}
		c.tools[block.ID] = block.Name
		return true
	}
	name, ok := block.Input["skill"].(string)
	if !ok || name == "" || block.ID == "" || c.prompt == "" || c.skills[block.ID] != nil {
		return false
	}
	for key, value := range block.Input {
		if key == "skill" {
			continue
		}
		if key != "args" {
			return false
		}
		if _, ok := value.(string); !ok {
			return false
		}
	}
	c.tools[block.ID] = "Skill"
	c.skills[block.ID] = &claudeInlineSkill{name: name, prompt: c.prompt}
	return true
}

func (c *claudeCompanions) observe(record claudeCompletionRecord, blocks []claudeInterruptedBlock) {
	text := claudeReportText(record.Message.Content)
	var native struct {
		Success     *bool  `json:"success"`
		CommandName string `json:"commandName"`
		Type        string `json:"type"`
	}
	_ = json.Unmarshal(record.ToolUseResult, &native)
	var fields map[string]json.RawMessage
	_ = json.Unmarshal(record.ToolUseResult, &fields)
	if record.Type == "user" && !record.Meta && !record.Compact && text != "" {
		c.prompt = record.PromptID
	}
	if record.Type == "attachment" {
		if source := c.images[record.Parent]; source != "" {
			c.images[record.UUID] = source
		} else if source := c.images[record.LogicalParent]; source != "" {
			c.images[record.UUID] = source
		}
	}
	if record.Type != "user" {
		return
	}
	for _, block := range blocks {
		if block.Type != "tool_result" {
			continue
		}
		if skill := c.skills[block.ToolUseID]; skill != nil && !block.IsError && len(fields) == 2 && native.Success != nil && *native.Success && native.CommandName == skill.name && record.PromptID == skill.prompt {
			skill.returned = true
		}
		if !block.IsError && c.tools[block.ToolUseID] == "Read" && native.Type == "image" && len(fields["file"]) > 0 {
			c.images[record.UUID] = record.PromptID
		}
	}
}

var claudeImageDimensions = regexp.MustCompile(`^\[Image: original [1-9][0-9]*x[1-9][0-9]*, displayed at [1-9][0-9]*x[1-9][0-9]*\. Multiply coordinates by [0-9]+(?:\.[0-9]+)? to map to original image\.\]$`)

func (c *claudeCompanions) accept(record claudeCompletionRecord, turn string) bool {
	if record.SessionID != c.binding.ProviderID {
		return false
	}
	if _, ok := reportDirectory(c.binding.Directory, record.Cwd); !ok {
		return false
	}
	if record.Type != "user" || !record.Meta || !record.TurnCompanion || record.PromptID != turn {
		return false
	}
	text := claudeReportText(record.Message.Content)
	if record.SourceToolUseID != "" {
		skill := c.skills[record.SourceToolUseID]
		if skill == nil || !skill.returned || skill.expanded || skill.prompt != turn {
			return false
		}
		first, _, hasBody := strings.Cut(text, "\n")
		path, hasPrefix := strings.CutPrefix(first, "Base directory for this skill: ")
		if !hasBody || !hasPrefix || !filepath.IsAbs(path) {
			return false
		}
		skill.expanded = true
		return true
	}
	var scalar string
	if json.Unmarshal(record.Message.Content, &scalar) != nil || !claudeImageDimensions.MatchString(scalar) {
		return false
	}
	return c.images[record.Parent] == turn || c.images[record.LogicalParent] == turn
}

func (c *claudeCompanions) settled() bool {
	for _, skill := range c.skills {
		if !skill.returned || !skill.expanded {
			return false
		}
	}
	return true
}
