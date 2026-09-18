// 会话身份与展示名。
//
// tmux 的 `session_name` 从此就是**会话 id**（2026-0728-1150-0142，由
// `session_created + session_id` 派生，见 internal/id）：不可变、server 内唯一、
// 没有 `-t` 前缀匹配的歧义。用户起的名字降级为纯展示属性 **label**，存在 tmux
// 会话级用户选项 `@roam_name` 里——随会话生死自动清理，CLI 与后端都能零成本读到，
// 不需要再维护一份「名字 → 会话」的台账。
//
// 于是：改名只改一个展示字段（不再有「主键搬家」）、显示名可以重复、logs/meta/
// group 台账全部按 id 存，改名一律不影响。
//
// 旧的按名字调用（cc-swarm 里的 `ttmux send <群>-<成员>`、外部脚本、老书签）
// 由 Resolve 兜住：label 与派生 id 都能反查回会话。
package runtime

import (
	"fmt"
	"sort"
	"strconv"
	"strings"

	"ttmux-cli-go/internal/id"
	"ttmux-cli-go/internal/memguard"
)

// LabelOption 会话展示名所在的 tmux 用户选项名。
const LabelOption = "@roam_name"

// SessionRow 一条 tmux 会话的身份：名字(=id) + 展示名 + 原始 tmux id + 创建时刻。
type SessionRow struct {
	Name    string // #{session_name}：新会话就是 Roami 会话 id
	Label   string // @roam_name：展示名，空则回退 Name
	TmuxID  string // #{session_id}，如 $3
	Created int64  // #{session_created}
}

// Display 展示口径：`名字（id）`。名字缺失时只给 id。
func (s SessionRow) Display() string {
	label := s.DisplayLabel()
	sid := s.ID()
	if label == "" || label == sid {
		return sid
	}
	return label + "(" + sid + ")"
}

// DisplayLabel 展示名（没设 @roam_name 的会话退回 tmux 名字）。
func (s SessionRow) DisplayLabel() string {
	if s.Label != "" {
		return s.Label
	}
	return s.Name
}

// ID 会话 id：名字本身已经是 id 就用它，否则（迁移前的老会话/裸 tmux 建的）现算派生 id。
func (s SessionRow) ID() string {
	if id.Valid(s.Name) {
		return s.Name
	}
	if v := id.ForSession(s.Created, s.TmuxID); v != "" {
		return v
	}
	return s.Name
}

// sessionRowFormat 一次问齐身份四元组。label 放最后：它是唯一可能含空格的字段，
// 万一用户塞了 tab 也只会污染自己（SanitizeLabel 已经防了，这里再兜一层）。
const sessionRowFormat = "#{session_id}\t#{session_created}\t#{session_name}\t#{" + LabelOption + "}"

// SessionRows 返回全部会话的身份行。tmux 没起/出错返回 nil——调用方据此进入
// 「盲态」：不解析、不迁移，宁可原样透传也不猜。
func (r Runtime) SessionRows() []SessionRow {
	out, err := r.TmuxOutput("list-sessions", "-F", sessionRowFormat)
	if err != nil {
		return nil
	}
	var rows []SessionRow
	for _, line := range strings.Split(strings.TrimRight(out, "\n"), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		parts := strings.SplitN(line, "\t", 4)
		if len(parts) < 3 {
			continue
		}
		created, _ := strconv.ParseInt(strings.TrimSpace(parts[1]), 10, 64)
		row := SessionRow{TmuxID: strings.TrimSpace(parts[0]), Created: created, Name: parts[2]}
		if len(parts) > 3 {
			row.Label = strings.TrimSpace(parts[3])
		}
		rows = append(rows, row)
	}
	return rows
}

// SessionRow 按 tmux 会话名取一行身份（不存在返回零值）。
func (r Runtime) SessionRow(name string) SessionRow {
	for _, s := range r.SessionRows() {
		if s.Name == name {
			return s
		}
	}
	return SessionRow{}
}

// Resolve 把用户/调用方给的 token 解析成 tmux 会话名（= 会话 id）。
// 顺序：精确会话名 > tmux id($3) > 展示名 > 派生 id（老书签/迁移前的名字）。
// 解析不出（或 tmux 盲态）时原样返回 token——让下游报「会话不存在」，
// 而不是在这里编一个会话出来。
func (r Runtime) Resolve(token string) string {
	token = strings.TrimSpace(token)
	if token == "" {
		return ""
	}
	rows := r.SessionRows()
	if rows == nil {
		return token
	}
	var byLabel []string
	for _, s := range rows {
		switch {
		case s.Name == token, s.TmuxID == token:
			return s.Name
		case s.Label == token:
			byLabel = append(byLabel, s.Name)
		}
	}
	if len(byLabel) > 0 {
		sort.Strings(byLabel) // 同名可以重复：取稳定的第一个（会话名有序 = 创建时刻有序）
		return byLabel[0]
	}
	for _, s := range rows {
		if s.ID() == token {
			return s.Name
		}
	}
	return token
}

// ResolveAlive 台账里读出来的会话名：活着就直接用（正常路径零额外 tmux 调用），
// 否则再按展示名/老名字解析一次——兼容迁移前写下的、按名字记的老台账。
func (r Runtime) ResolveAlive(name string) string {
	if name == "" || r.HasSession(name) {
		return name
	}
	if n := r.Resolve(name); n != "" && r.HasSession(n) {
		return n
	}
	return name
}

// ResolveAll 批量解析（去重保序），供 kill/send 这类吃多个目标的入口用。
func (r Runtime) ResolveAll(tokens []string) []string {
	seen := map[string]bool{}
	out := make([]string, 0, len(tokens))
	for _, t := range tokens {
		n := r.Resolve(t)
		if n == "" || seen[n] {
			continue
		}
		seen[n] = true
		out = append(out, n)
	}
	return out
}

// SanitizeLabel 展示名去掉制表符/换行（会破坏 list-sessions -F 的分隔）。
// 除此之外一律原样保留：中文、空格、点号、冒号都行——它不再是 tmux 目标。
func SanitizeLabel(label string) string {
	return strings.TrimSpace(strings.NewReplacer("\t", " ", "\r", " ", "\n", " ").Replace(label))
}

// SetSessionLabel 设置会话展示名。target 用 tmux id($3) 或裸会话名——
// 注意 `set-option -t` **不认** `=name` 的精确前缀（tmux 3.4 报 no such session）。
func (r Runtime) SetSessionLabel(target, label string) error {
	label = SanitizeLabel(label)
	if target == "" {
		return fmt.Errorf("empty target")
	}
	if label == "" {
		return r.Tmux("set-option", "-t", target, "-u", LabelOption)
	}
	return r.Tmux("set-option", "-t", target, LabelOption, label)
}

// SessionLabel 读会话展示名（没设过则回退 tmux 会话名）。
func (r Runtime) SessionLabel(name string) string {
	return r.SessionRow(name).DisplayLabel()
}

// CreateOpts 建会话的参数。Label 是展示名（可空 = 不设，展示时退回 id）。
type CreateOpts struct {
	Label  string
	Dir    string
	Width  string // -x，空则不传
	Height string // -y，空则不传
	Extra  []string
}

// CreateSession 建一个 detached 会话并返回它的会话名（= 会话 id）。
//
// 先不带 -s 建（tmux 临时给个数字名），用 -P -F 把 session_id/created 取回来，
// 派生出 id 再 rename——这样 id 与 `$N` 始终一一对应、可反解，与 `ls` 一直以来
// 展示的 id 是同一个值（老书签/URL 不失效）。中间那个数字名只存在几毫秒。
func (r Runtime) CreateSession(opt CreateOpts) (string, error) {
	args := []string{"new-session", "-d", "-P", "-F", "#{session_id}\t#{session_created}"}
	if opt.Dir != "" {
		args = append(args, "-c", opt.Dir)
	}
	if opt.Width != "" {
		args = append(args, "-x", opt.Width)
	}
	if opt.Height != "" {
		args = append(args, "-y", opt.Height)
	}
	args = append(args, opt.Extra...)
	out, err := r.TmuxOutput(args...)
	if err != nil {
		return "", fmt.Errorf("new-session 失败: %s", strings.TrimSpace(out))
	}
	tmuxID, createdStr, ok := strings.Cut(strings.TrimSpace(lastLine(out)), "\t")
	if !ok || tmuxID == "" {
		return "", fmt.Errorf("new-session 未返回 session_id: %s", strings.TrimSpace(out))
	}
	created, _ := strconv.ParseInt(strings.TrimSpace(createdStr), 10, 64)
	sess := id.ForSession(created, tmuxID)
	if sess == "" || sess == tmuxID { // 派生不出（数据不全）：退回随机 id，别把 `$3` 当会话名
		sess = id.NewAt(r.Now())
	}
	if err := r.Tmux("rename-session", "-t", tmuxID, sess); err != nil {
		// 改名失败（极罕见）：会话还在，用 tmux 给的临时名兜底，别把它漏成孤儿
		return r.sessionNameByID(tmuxID), err
	}
	if opt.Label != "" {
		_ = r.SetSessionLabel(tmuxID, opt.Label)
	}
	// 内存天花板：撞顶时 cgroup OOM 只杀这个会话里的进程，不再把整台机器带走。
	// 装不上（无 systemd / 控制器没委派）就静默跳过——护栏失效该降级成「和以前一样」。
	r.GuardMemory(sess)
	return sess, nil
}

// GuardMemory 给会话的所有 pane 套上内存上限。
//
// 新 pane（split-window / new-window）有自己的 scope，也得补设，所以这里按会话
// 遍历而不是只管第一个 pane；调用方在建会话后、以及 Reconcile 巡检时都会经过。
func (r Runtime) GuardMemory(sess string) {
	// 额度来自设置页写的 env 文件，环境变量可临时覆盖（见 EnvValue）。
	l := memguard.From(r.EnvValue(memguard.EnvMax), r.EnvValue(memguard.EnvHigh), r.EnvValue(memguard.EnvSwap))
	if l.Off() {
		return
	}
	for _, pid := range r.PanePIDs(sess) {
		_ = memguard.Apply(pid, l)
	}
}

// PanePIDs 返回会话里每个 pane 的进程号。
// -s = 这个会话内的所有 pane（不是 -a，那是整个 server 的，会把别人的 pane 也算进来）。
func (r Runtime) PanePIDs(sess string) []int {
	out, err := r.TmuxOutput("list-panes", "-s", "-t", "="+sess, "-F", "#{pane_pid}")
	if err != nil {
		return nil
	}
	var pids []int
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		if n, err := strconv.Atoi(strings.TrimSpace(line)); err == nil && n > 0 {
			pids = append(pids, n)
		}
	}
	return pids
}

// sessionNameByID 反查 tmux id 现在的会话名（查不到返回空串）。
func (r Runtime) sessionNameByID(tmuxID string) string {
	out, err := r.TmuxOutput("display-message", "-t", tmuxID, "-p", "#{session_name}")
	if err != nil {
		return ""
	}
	return strings.TrimSpace(out)
}

func lastLine(s string) string {
	lines := strings.Split(strings.TrimRight(s, "\n"), "\n")
	return lines[len(lines)-1]
}

// SessionState 一条会话的「此刻」：身份 + 有没有人看着 + 最后一次有动静是啥时候。
//
// 和 SessionRows 分开一个格式串，是因为两者问的问题不同：那个问身份（谁是谁），
// 这个问状态（还动不动）。合并的代价是所有拿身份的调用方都多付两次字段解析，
// 而分开的代价只是多一行常量——label 必须留在最后（唯一可能带空白的字段）。
type SessionState struct {
	SessionRow
	Attached bool  // 有客户端 attach 着
	Activity int64 // 最后一次有动静（unix 秒）
}

// sessionStateFormat：label 仍放最后，理由同 sessionRowFormat。
const sessionStateFormat = "#{session_id}\t#{session_created}\t#{session_activity}\t" +
	"#{window_activity}\t#{session_attached}\t#{session_name}\t#{" + LabelOption + "}"

// SessionStates 返回全部活会话的状态。tmux 盲态返回 nil——同 SessionRows，
// 「看不见的时候不下判断」。
//
// activity 取 session_activity 与 window_activity 的较大者：tmux 只在
// attach/输入/焦点变化时刷新 session_activity，后台没人看的会话即便一直在输出
// （agent 正干活）也不动，光看前者会把干得最欢的会话判成「安静了一天」。
func (r Runtime) SessionStates() []SessionState {
	out, err := r.TmuxOutput("list-sessions", "-F", sessionStateFormat)
	if err != nil {
		return nil
	}
	var states []SessionState
	for _, line := range strings.Split(strings.TrimRight(out, "\n"), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		parts := strings.SplitN(line, "\t", 7)
		if len(parts) < 6 {
			continue
		}
		created, _ := strconv.ParseInt(strings.TrimSpace(parts[1]), 10, 64)
		sa, _ := strconv.ParseInt(strings.TrimSpace(parts[2]), 10, 64)
		wa, _ := strconv.ParseInt(strings.TrimSpace(parts[3]), 10, 64)
		attached, _ := strconv.Atoi(strings.TrimSpace(parts[4]))
		st := SessionState{
			SessionRow: SessionRow{TmuxID: strings.TrimSpace(parts[0]), Created: created, Name: parts[5]},
			Attached:   attached > 0,
			Activity:   max64(sa, wa),
		}
		if len(parts) > 6 {
			st.Label = strings.TrimSpace(parts[6])
		}
		states = append(states, st)
	}
	return states
}

func max64(a, b int64) int64 {
	if a > b {
		return a
	}
	return b
}
