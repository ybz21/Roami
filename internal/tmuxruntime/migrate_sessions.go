package runtime

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"

	"github.com/ybz21/Roami/internal/id"
)

// sessionIDMigrationMark 迁移完成标记（幂等开关）。
const sessionIDMigrationMark = "session-id.done"

func (r Runtime) migrationMarkPath() string {
	return filepath.Join(r.DataDir, "migrations", sessionIDMigrationMark)
}

// SessionIDMigrationDone 迁移是否已经做过（做过就一次 os.Stat 走人）。
func (r Runtime) SessionIDMigrationDone() bool {
	_, err := os.Stat(r.migrationMarkPath())
	return err == nil
}

// MigrateSessionsToID 把存量会话改名成会话 id，原名转存为展示名（@roam_name）。
//
// 会话名从此是不可变 id，名字只是展示属性——存量会话也要对齐这个口径，否则同一台
// 机器上两套命名混着，`ls` 一半显示 id 一半显示名字，按名字派生的 logs/meta 也两套。
//
// 顺序有讲究：**先设 @roam_name 再改名**。改名后所有按老名字来的调用（正在跑的
// 蜂群指挥、外部脚本、用户手里的命令）都靠 Resolve 按展示名反查命中，中间不能有
// 「已改名但还没展示名」的窗口。
//
// 派生数据一并搬家：logs/<名>.log、meta/<名>/、cc-swarm/<名>.brief.md、
// groups/*.group 里的成员行。返回 {老名字: 新会话名}，供调用方改写自己的台账
// （蜂群 members.session / supervisor、插件会话表——那些包 import 了 runtime，
// 反过来不能 import，所以由 app 层串起来）。
//
// tmux 盲态（server 没起/读不到会话）时**什么都不做也不写标记**，下次再来——
// 与 sessmeta 的 v1 迁移同一口径：宁可晚一次，也不在看不见的时候乱搬。
func (r Runtime) MigrateSessionsToID() map[string]string {
	if r.SessionIDMigrationDone() {
		return nil
	}
	rows := r.SessionRows()
	if rows == nil {
		return nil // 盲态：不迁移、不写标记
	}
	// 只改**自己台账里认得的**会话。tmux server 是公共的：别的 Roami 实例（另一个
	// ROAM_HOME）、测试、用户手搓的临时会话都可能在同一个 server 上，改名它们属于
	// 越界——而且会让「按名字定位」的旁路（别人的脚本、别人的测试）当场断掉。
	owned := r.knownSessions()
	mapping := map[string]string{}
	for _, row := range rows {
		if id.Valid(row.Name) || strings.HasPrefix(row.Name, "_ttmux-") {
			continue // 已经是 id / 基础设施单例（靠固定名判存活，不能动）
		}
		if !owned[row.Name] {
			continue
		}
		newName := row.ID()
		if newName == "" || newName == row.Name || !id.Valid(newName) {
			continue // 派生不出 id（tmux 数据不全）：宁可不动
		}
		if row.Label == "" {
			_ = r.SetSessionLabel(row.TmuxID, row.Name)
		}
		if err := r.Tmux("rename-session", "-t", row.TmuxID, newName); err != nil {
			continue
		}
		mapping[row.Name] = newName
		r.moveTaskArtifacts(row.Name, newName)
	}
	r.rewriteGroupFiles(mapping)
	_ = os.MkdirAll(filepath.Dir(r.migrationMarkPath()), 0o755)
	_ = os.WriteFile(r.migrationMarkPath(), []byte("v1\n"), 0o644)
	return mapping
}

// knownSessions 本实例台账里出现过的会话名：
//   - `session-homes.json` 的名字快照（Web/编排建的会话 + 后端采样过的全部活会话）
//   - `groups/*.group` 的成员（spawn 任务组与蜂群成员）
//   - `meta/<名>/` 任务元数据目录
//
// 空台账（全新 ROAM_HOME / 测试沙盒）自然得到空集合 → 一个会话都不动。
func (r Runtime) knownSessions() map[string]bool {
	known := map[string]bool{}
	var homes struct {
		Homes map[string]struct {
			Name string `json:"name"`
		} `json:"homes"`
	}
	if b, err := os.ReadFile(filepath.Join(r.DataDir, "session-homes.json")); err == nil {
		if json.Unmarshal(b, &homes) == nil {
			for _, row := range homes.Homes {
				if row.Name != "" {
					known[row.Name] = true
				}
			}
		}
		// v1 老文件是 {会话名: 目录}
		var v1 map[string]string
		if json.Unmarshal(b, &v1) == nil {
			for name := range v1 {
				if name != "v" && name != "homes" {
					known[name] = true
				}
			}
		}
	}
	files, _ := filepath.Glob(filepath.Join(r.GroupsDir, "*.group"))
	for _, f := range files {
		b, err := os.ReadFile(f)
		if err != nil {
			continue
		}
		for _, line := range strings.Split(string(b), "\n") {
			if s := strings.TrimSpace(line); s != "" {
				known[s] = true
			}
		}
	}
	if entries, err := os.ReadDir(r.MetaDir); err == nil {
		for _, e := range entries {
			if e.IsDir() {
				known[e.Name()] = true
			}
		}
	}
	return known
}

// moveTaskArtifacts 把按老会话名派生的文件搬到新名下（目标已存在就不覆盖）。
func (r Runtime) moveTaskArtifacts(old, neu string) {
	rename := func(from, to string) {
		if from == to {
			return
		}
		if _, err := os.Stat(from); err != nil {
			return
		}
		if _, err := os.Stat(to); err == nil {
			return
		}
		_ = os.Rename(from, to)
	}
	rename(r.LogFile(old), r.LogFile(neu))
	rename(filepath.Join(r.LogsDir, old+".prompt"), filepath.Join(r.LogsDir, neu+".prompt"))
	rename(filepath.Join(r.DataDir, "cc-swarm", old+".brief.md"), filepath.Join(r.DataDir, "cc-swarm", neu+".brief.md"))
	rename(r.TaskMetaDir(old), r.TaskMetaDir(neu))
	rename(filepath.Join(r.DataDir, "agents", old), filepath.Join(r.DataDir, "agents", neu))
	// 任务的语义名（`<组>-<成员>`）落一份，会话死后 status/collect 还要拿它显示
	if _, err := os.Stat(r.TaskMetaDir(neu)); err == nil {
		labelFile := filepath.Join(r.TaskMetaDir(neu), "label.txt")
		if _, err := os.Stat(labelFile); err != nil {
			_ = os.WriteFile(labelFile, []byte(old+"\n"), 0o644)
		}
	}
}

// rewriteGroupFiles 把任务组台账里的老会话名换成新会话名（逐行精确匹配）。
func (r Runtime) rewriteGroupFiles(mapping map[string]string) {
	if len(mapping) == 0 {
		return
	}
	files, _ := filepath.Glob(filepath.Join(r.GroupsDir, "*.group"))
	for _, f := range files {
		b, err := os.ReadFile(f)
		if err != nil {
			continue
		}
		lines := strings.Split(string(b), "\n")
		changed := false
		for i, line := range lines {
			name := strings.TrimSpace(line)
			if neu, ok := mapping[name]; ok && name != "" {
				lines[i] = neu
				changed = true
			}
		}
		if changed {
			_ = os.WriteFile(f, []byte(strings.Join(lines, "\n")), 0o644)
		}
	}
}
