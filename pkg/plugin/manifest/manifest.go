// Package manifest defines the plugin manifest model (roam-plugin.json /
// builtin 声明,docs/design/plugin/05-manifest.md 的子集)。放在公开 pkg 下:
// builtin Go 插件在自己的包里声明 manifest 并向 sdk 自注册,不必改宿主
// internal 代码;宿主 internal/plugin 经类型别名复用同一套模型。
package manifest

import (
	"fmt"
	"strings"
)

// LocaleText is a locale-keyed display string ({"zh-CN": ..., "en-US": ...}).
type LocaleText map[string]string

// Get returns the text for locale, falling back to zh-CN then any.
func (l LocaleText) Get(locale string) string {
	if l == nil {
		return ""
	}
	if v := l[locale]; v != "" {
		return v
	}
	if v := l["zh-CN"]; v != "" {
		return v
	}
	for _, v := range l {
		return v
	}
	return ""
}

// Manifest mirrors roam-plugin.json (docs/design/plugin/05-manifest.md 的子集).
type Manifest struct {
	ManifestVersion  int        `json:"manifestVersion"`
	ID               string     `json:"id"`
	Publisher        string     `json:"publisher"`
	Name             string     `json:"name"`
	DisplayName      LocaleText `json:"displayName,omitempty"`
	Version          string     `json:"version"`
	Description      LocaleText `json:"description,omitempty"`
	Main             string     `json:"main,omitempty"`
	Runtime          Runtime    `json:"runtime"`
	Permissions      Perms      `json:"permissions"`
	ActivationEvents []string   `json:"activationEvents,omitempty"`
	Contributes      Contribs   `json:"contributes"`
}

// Runtime describes how the plugin process is launched.
type Runtime struct {
	Kind     string `json:"kind"` // builtin | node | exec
	Resident bool   `json:"resident,omitempty"`
}

// Perms is the declared permission ceiling (v1 宿主 API 侧强制,见 07-security).
type Perms struct {
	Workspace     []string     `json:"workspace,omitempty"` // read | write
	Commands      CommandPerms `json:"commands,omitempty"`
	Network       NetworkPerms `json:"network,omitempty"`
	Sessions      []string     `json:"sessions,omitempty"`      // read | write
	Agents        []string     `json:"agents,omitempty"`        // spawn
	Findings      []string     `json:"findings,omitempty"`      // read | write
	Notifications []string     `json:"notifications,omitempty"` // publish | subscribe
	Secrets       []string     `json:"secrets,omitempty"`
}

// CommandPerms whitelists host-executed commands by argv prefix.
type CommandPerms struct {
	Allow []string `json:"allow,omitempty"`
	Deny  []string `json:"deny,omitempty"`
}

// NetworkPerms declares outbound domains (v1 仅声明与审计,不阻断).
type NetworkPerms struct {
	AllowedDomains []string `json:"allowedDomains,omitempty"`
}

// Contribs are the static contribution points.
type Contribs struct {
	Commands          []CommandContrib `json:"commands,omitempty"`
	NotificationSinks []SinkContrib    `json:"notificationSinks,omitempty"`
	ConfigGroups      []ConfigGroup    `json:"configGroups,omitempty"`
	ConfigFields      []ConfigField    `json:"configFields,omitempty"`
	StatusItems       []StatusItem     `json:"statusItems,omitempty"`
}

// StatusItem 声明一格底部状态条(docs/design/web/20-status-bar §05)。
//
// 声明式而非代码式:插件是外部进程,不可能让它渲染宿主的 DOM。插件只给数值,
// 宿主用固定的四种渲染器画、按声明的阈值判红黄绿——**severity 不由插件说**,
// 否则每个插件都会把自己染红,第三格红的出现时这条就报废了。
type StatusItem struct {
	ID     string     `json:"id"`                 // 插件内唯一;全局 id 是 <插件id>/<id>
	Title  LocaleText `json:"title,omitempty"`    // 格前的短标签(「内存」),也是设置页里的名字
	Align  string     `json:"align,omitempty"`    // left(默认) | right;插件只能落 left-tail / right-head
	Prio   int        `json:"priority,omitempty"` // 段内从大到小;同分按全局 id 字典序(稳定)
	Tier   int        `json:"tier,omitempty"`     // 折叠档位 1..4,越小越晚被丢;缺省 3
	Render string     `json:"render,omitempty"`   // text | gauge | dot | progress;缺省 text
	Icon   string     `json:"icon,omitempty"`     // icons.tsx 里的导出名;不认识的名字宿主忽略
	Unit   string     `json:"unit,omitempty"`     // percent | bytes | bytesPerSec | celsius | count
	Source StatusSrc  `json:"source"`
	Thresh *StatusThr `json:"thresholds,omitempty"`
	Click  *StatusAct `json:"onClick,omitempty"`
}

// StatusSrc 是取值方式。默认拉:宿主按 Refresh 调 Command,再从返回的 JSON
// 里按 Path 取值。同一插件的多个 item 若 Command 相同,合并成一次调用——
// 主机监控六格共用一次 stats,不是六次。
type StatusSrc struct {
	Command string `json:"command,omitempty"` // 短名形式(host-monitor.stats)
	Refresh int    `json:"refresh,omitempty"` // 秒;下限 StatusMinRefresh
	Path    string `json:"path,omitempty"`    // 点分路径,支持 a.b[0].c
	// Text 是可选的第二条路径:取到就直接当文案用,不再由宿主按 Unit 格式化。
	TextPath string `json:"textPath,omitempty"`
	// Total 配合 unit=bytesRatio:Path 取已用、TotalPath 取总量,画成「12.1/32G」,
	// 迷你条与阈值都按两者的比例算。一个百分比说不出「还剩多少」,而那才是你要的。
	TotalPath string `json:"totalPath,omitempty"`
	Push      bool   `json:"push,omitempty"` // 常驻插件主动推(runtime.resident 才有意义)
}

// StatusThr 是阈值。SustainSec>0 时要求连续越线这么久才升级——CPU 天天冲
// 100%(编译、跑测试都是正常干活),按瞬时值上色两天内就没人再看这条了。
type StatusThr struct {
	Warn       *float64 `json:"warn,omitempty"`
	Danger     *float64 `json:"danger,omitempty"`
	SustainSec int      `json:"sustainSec,omitempty"`
	// Invert:值越小越糟(如剩余磁盘)。缺省 false = 越大越糟。
	Invert bool `json:"invert,omitempty"`
}

// StatusAct 是点击动作。只有白名单里的几种,插件给不了任意跳转。
type StatusAct struct {
	Kind string `json:"kind"`         // pluginView | route
	ID   string `json:"id,omitempty"` // pluginView: 插件 id;route: 形如 #/files 的站内路由
}

// 状态条贡献点的预算(20-status-bar §05)。一条 24px 的槽装不下三个插件各五格,
// 所以格数、刷新率都在 manifest 校验期就管住,而不是等运行时再讲道理。
const (
	StatusMaxItemsPlugin  = 2 // 第三方插件
	StatusMaxItemsBuiltin = 6 // 随二进制分发的 builtin 插件
	StatusMinRefresh      = 2 // 秒;plugin run 每次起一个子进程
	StatusMaxTitleLen     = 24
)

// ConfigGroup 把配置字段分节展示(如飞书桥的「出站通知」与「入站派活」是
// 两条独立通道);设置页按声明顺序渲染分组标题与引导说明。
type ConfigGroup struct {
	Key         string     `json:"key"`
	Title       LocaleText `json:"title,omitempty"`
	Description LocaleText `json:"description,omitempty"` // 支持多行(\n 即换行),写配置步骤
}

// ConfigField declares one settings entry; 宿主(CLI/Web 设置页)据此渲染
// 配置表单,插件零前端(完整 JSON Schema 校验为后续增量)。
type ConfigField struct {
	Key         string     `json:"key"`
	Group       string     `json:"group,omitempty"` // 所属 ConfigGroup.Key;空=默认组
	Title       LocaleText `json:"title,omitempty"`
	Description LocaleText `json:"description,omitempty"`
	Secret      bool       `json:"secret,omitempty"`  // 展示打码,输入用密码框
	Options     []string   `json:"options,omitempty"` // 非空则渲染为下拉选择
	Placeholder string     `json:"placeholder,omitempty"`
}

// CommandContrib declares a human-facing command (CLI / Web).
type CommandContrib struct {
	ID    string     `json:"id"`
	Title LocaleText `json:"title,omitempty"`
}

// SinkContrib subscribes the plugin to notification types as an outbound sink.
type SinkContrib struct {
	ID     string   `json:"id"`
	Events []string `json:"events,omitempty"` // notification types; "*" matches all
}

// Validate checks structural invariants shared by builtin and external plugins.
func (m Manifest) Validate() error {
	if m.ID == "" || !strings.Contains(m.ID, ".") {
		return fmt.Errorf("manifest: id must be <publisher>.<name>, got %q", m.ID)
	}
	// 冒号是 id 限定调用形式(<id>:<handler>)的保留分隔符:id 含冒号会让
	// FullCommandOwner 按第一个冒号切出的 id 永远对不上,限定调用全挂
	if strings.Contains(m.ID, ":") {
		return fmt.Errorf("manifest: id must not contain ':', got %q", m.ID)
	}
	if m.Version == "" {
		return fmt.Errorf("manifest %s: version is required", m.ID)
	}
	switch m.Runtime.Kind {
	case "builtin":
	case "node", "exec":
		if m.Main == "" {
			return fmt.Errorf("manifest %s: main is required for runtime.kind=%s", m.ID, m.Runtime.Kind)
		}
	default:
		return fmt.Errorf("manifest %s: unsupported runtime.kind %q", m.ID, m.Runtime.Kind)
	}
	seen := map[string]bool{}
	for _, c := range m.Contributes.Commands {
		if !strings.HasPrefix(c.ID, m.commandPrefix()) {
			return fmt.Errorf("manifest %s: command id %q must be prefixed %q", m.ID, c.ID, m.commandPrefix())
		}
		// 冒号是 id 限定调用形式(<id>:<handler>)的保留分隔符
		if strings.Contains(c.ID, ":") {
			return fmt.Errorf("manifest %s: command id %q must not contain ':'", m.ID, c.ID)
		}
		if seen[c.ID] {
			return fmt.Errorf("manifest %s: duplicate command id %q", m.ID, c.ID)
		}
		seen[c.ID] = true
	}
	if err := m.validateStatusItems(); err != nil {
		return err
	}
	return nil
}

// validateStatusItems 管住状态条贡献点的预算与取值枚举。
func (m Manifest) validateStatusItems() error {
	items := m.Contributes.StatusItems
	if len(items) == 0 {
		return nil
	}
	max := StatusMaxItemsPlugin
	if m.Runtime.Kind == "builtin" {
		max = StatusMaxItemsBuiltin
	}
	if len(items) > max {
		return fmt.Errorf("manifest %s: %d statusItems exceeds the limit of %d", m.ID, len(items), max)
	}
	seen := map[string]bool{}
	for _, it := range items {
		if it.ID == "" {
			return fmt.Errorf("manifest %s: statusItem id is required", m.ID)
		}
		if strings.ContainsAny(it.ID, "/:") {
			return fmt.Errorf("manifest %s: statusItem id %q must not contain '/' or ':'", m.ID, it.ID)
		}
		if seen[it.ID] {
			return fmt.Errorf("manifest %s: duplicate statusItem id %q", m.ID, it.ID)
		}
		seen[it.ID] = true
		switch it.Align {
		case "", "left", "right":
		default:
			return fmt.Errorf("manifest %s: statusItem %q has unsupported align %q", m.ID, it.ID, it.Align)
		}
		switch it.Render {
		case "", "text", "gauge", "dot", "progress":
		default:
			return fmt.Errorf("manifest %s: statusItem %q has unsupported render %q", m.ID, it.ID, it.Render)
		}
		if it.Tier < 0 || it.Tier > 4 {
			return fmt.Errorf("manifest %s: statusItem %q has tier %d, want 1..4", m.ID, it.ID, it.Tier)
		}
		if !it.Source.Push {
			if it.Source.Command == "" {
				return fmt.Errorf("manifest %s: statusItem %q needs source.command (or source.push)", m.ID, it.ID)
			}
			if _, ok := m.CommandOwner(it.Source.Command); !ok {
				return fmt.Errorf("manifest %s: statusItem %q references undeclared command %q", m.ID, it.ID, it.Source.Command)
			}
			if it.Source.Refresh > 0 && it.Source.Refresh < StatusMinRefresh {
				return fmt.Errorf("manifest %s: statusItem %q refresh %ds is below the %ds floor", m.ID, it.ID, it.Source.Refresh, StatusMinRefresh)
			}
			if it.Source.Path == "" && it.Source.TextPath == "" {
				return fmt.Errorf("manifest %s: statusItem %q needs source.path or source.textPath", m.ID, it.ID)
			}
		}
		if it.Click != nil {
			switch it.Click.Kind {
			case "pluginView", "route":
			default:
				return fmt.Errorf("manifest %s: statusItem %q has unsupported onClick.kind %q", m.ID, it.ID, it.Click.Kind)
			}
		}
	}
	return nil
}

// commandPrefix is "<name>." — 插件命令按短名前缀(如 review-mesh.review)。
func (m Manifest) commandPrefix() string { return m.Name + "." }

// CommandOwner reports whether commandID belongs to this manifest and returns
// the bare handler name (without prefix).
func (m Manifest) CommandOwner(commandID string) (string, bool) {
	if rest, ok := strings.CutPrefix(commandID, m.commandPrefix()); ok {
		for _, c := range m.Contributes.Commands {
			if c.ID == commandID {
				return rest, true
			}
		}
	}
	return "", false
}

// FullCommandOwner is CommandOwner for the id-qualified form
// "<id>:<handler>"(如 roam.host-monitor:stats):把命令钉死在这个插件上。
// 短名前缀(host-monitor.stats)在多 publisher 撞短名时会被最先匹配者接走,
// 调用方(如 Web 按路由里的插件 id 调命令)需要精确归属时用这个形式。
// 分隔符用冒号:命令 ID 禁含冒号(见 Validate),与点分短名不存在歧义——
// 点分限定形式(<id>.<handler>)会和「短名恰为 <id 前缀> 的插件」的命令
// 撞出解析二义。
func (m Manifest) FullCommandOwner(commandID string) (string, bool) {
	id, handler, ok := strings.Cut(commandID, ":")
	if !ok || id != m.ID {
		return "", false
	}
	return m.CommandOwner(m.commandPrefix() + handler)
}

// SinkMatches reports whether the plugin subscribes to a notification type.
func (m Manifest) SinkMatches(notifType string) bool {
	for _, s := range m.Contributes.NotificationSinks {
		for _, e := range s.Events {
			if e == "*" || e == notifType {
				return true
			}
		}
	}
	return false
}

// HasPerm checks a "<domain>:<action>" grant against the declared ceiling.
func (m Manifest) HasPerm(perm string) bool {
	domain, action, _ := strings.Cut(perm, ":")
	in := func(list []string) bool {
		for _, v := range list {
			if v == action {
				return true
			}
		}
		return false
	}
	switch domain {
	case "workspace":
		return in(m.Permissions.Workspace)
	case "sessions":
		return in(m.Permissions.Sessions)
	case "agents":
		return in(m.Permissions.Agents)
	case "findings":
		return in(m.Permissions.Findings)
	case "notifications":
		return in(m.Permissions.Notifications)
	case "commands":
		return len(m.Permissions.Commands.Allow) > 0
	}
	return false
}

// CommandAllowed enforces the argv-prefix whitelist for command.exec.
func (m Manifest) CommandAllowed(argv []string) bool {
	if len(argv) == 0 {
		return false
	}
	joined := strings.Join(argv, " ")
	for _, d := range m.Permissions.Commands.Deny {
		if strings.HasPrefix(joined, d) {
			return false
		}
	}
	for _, a := range m.Permissions.Commands.Allow {
		if strings.HasPrefix(joined, a) {
			return true
		}
	}
	return false
}
