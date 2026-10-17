// prompt.go：蜂群成员的提示词模板渲染（Go 标准库 text/template，零依赖）。
//
// 后端在「加成员」时按角色(leader/member)渲染出完整 prompt，作为任务传给
// `roami session swarm add`；CLI 收到的即最终 prompt（不再二次模板）。模板内置于二进制，
// 可用 TTMUX_PROMPT_DIR 指向外部目录覆盖；skill 目录用 TTMUX_SKILLS_DIR（默认 ~/.claude/skills）。
package api

import (
	"bytes"
	"embed"
	"os"
	"path/filepath"
	"strings"
	"text/template"
)

//go:embed prompts/*.tmpl prompts/roles/*.md
var promptFS embed.FS

// promptCtx 是模板渲染上下文。
type promptCtx struct {
	Swarm, Goal, Member, Role, Kind string
	Task, Deps, Workdir, SkillsDir  string
	MasterName                      string
	Peers                           []string
	Subrole, SubroleLabel, Duty     string   // 细分角色 key/中文 + 长期职责
	RoleTrait                       string   // prompts/roles/<subrole>.md 渲染前注入（角色工作方式）
	Roster                          []string // 项目页发起时的班子建议（仅供指挥参考，09 设计 §4）
	WorktreePolicy                  bool     // 成员独立 worktree 约定（写进开场白，指挥执行）
}

// skillsDir 返回 agent 自动加载 skill 的目录（install.sh / start.sh --dev 同步到此）。
func skillsDir() string {
	if d := os.Getenv("TTMUX_SKILLS_DIR"); d != "" {
		return d
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".claude", "skills")
}

// renderMemberPrompt 按角色选模板并渲染；失败时返回空串（调用方回退到原始任务）。
// 渲染前把细分角色归一、补 label，并读入 prompts/roles/<key>.md 角色片段 → RoleTrait。
func renderMemberPrompt(ctx promptCtx) string {
	if ctx.Subrole != "" {
		ctx.Subrole = subroleNorm(ctx.Subrole)
		ctx.SubroleLabel = subroleLabel(ctx.Subrole)
		ctx.RoleTrait = roleTrait(ctx.Subrole)
	}
	name := "worker.md.tmpl"
	if ctx.Role == "leader" || ctx.Role == "master" {
		name = "master.md.tmpl"
	}
	return renderPrompt(name, ctx)
}

// roleTrait 读取 prompts/roles/<key>.md（自定义/未命中 → 空串）。
// 支持 TTMUX_PROMPT_DIR 覆盖；内置嵌入到二进制。
func roleTrait(key string) string {
	rel := "prompts/roles/" + key + ".md"
	if dir := os.Getenv("TTMUX_PROMPT_DIR"); dir != "" {
		if data, err := os.ReadFile(filepath.Join(dir, "roles", key+".md")); err == nil {
			return strings.TrimSpace(string(data))
		}
	}
	if data, err := promptFS.ReadFile(rel); err == nil {
		return strings.TrimSpace(string(data))
	}
	return ""
}

// renderLeaderKickoff 渲染「自动拉起的 Leader」开场白（swarm new / adopt 时用）。
// 与 master.md.tmpl 不同：它没有起步任务，要从目标走完整生命周期（拆任务→派活→巡检→集成），
// 所以单独用 auto_leader.md.tmpl，并强调「编排而非单干」。失败返回空串，CLI 回退到 /cc-swarm。
func renderLeaderKickoff(ctx promptCtx) string {
	return renderPrompt("auto_leader.md.tmpl", ctx)
}

// renderPrompt 读取并渲染 prompts/<name>（TTMUX_PROMPT_DIR 可覆盖内置模板）。
func renderPrompt(name string, ctx promptCtx) string {
	var raw []byte
	if dir := os.Getenv("TTMUX_PROMPT_DIR"); dir != "" {
		if data, err := os.ReadFile(filepath.Join(dir, name)); err == nil {
			raw = data
		}
	}
	if raw == nil {
		data, err := promptFS.ReadFile("prompts/" + name)
		if err != nil {
			return ""
		}
		raw = data
	}
	t, err := template.New(name).Parse(string(raw))
	if err != nil {
		return ""
	}
	var out bytes.Buffer
	if err := t.Execute(&out, ctx); err != nil {
		return ""
	}
	return strings.TrimSpace(out.String())
}
