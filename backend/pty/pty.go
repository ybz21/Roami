// Package pty 桥接 tmux attach ↔ 浏览器 xterm.js（WebSocket + creack/pty）。
// 每个会话 = 一个实时命令行。关闭 WS 只 detach，不杀 session。
package pty

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	creackpty "github.com/creack/pty"
	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
)

// utf8Env 保证 tmux 客户端 locale 为 UTF-8。tmux 按客户端 LC_ALL/LC_CTYPE/LANG 是否含 UTF-8
// 决定能否渲染中文等宽字符，pane 里的 ls 也依赖它正确输出文件名；后端进程常跑在 C/POSIX
// locale 下（服务化部署），不补就会满屏乱码。仅在现有 locale 非 UTF-8 时追加 C.UTF-8，尊重已有设置。
func utf8Env(env []string) []string {
	get := func(k string) (string, bool) {
		p := k + "="
		for i := len(env) - 1; i >= 0; i-- { // 后出现的覆盖前面的
			if strings.HasPrefix(env[i], p) {
				return env[i][len(p):], true
			}
		}
		return "", false
	}
	eff := ""
	if v, ok := get("LC_ALL"); ok && v != "" {
		eff = v
	} else if v, ok := get("LC_CTYPE"); ok && v != "" {
		eff = v
	} else if v, ok := get("LANG"); ok {
		eff = v
	}
	u := strings.ToUpper(eff)
	if strings.Contains(u, "UTF-8") || strings.Contains(u, "UTF8") {
		return env
	}
	return append(env, "LC_ALL=C.UTF-8")
}

// 有效窗口尺寸下限：前端布局未就绪 / 面板折叠 / 离屏挂载时会算出极窄的 cols(如 2)，
// 因 window-size=latest 会把共享会话挤成窄条，且客户端断开后仍卡住。
const (
	minCols = 20
	minRows = 6
)

// SanitizeSessionName 替换 tmux 会话名中的 '.' 和 ':'，避免 -t 解析出错。
func SanitizeSessionName(name string) string {
	return strings.NewReplacer(".", "_", ":", "_").Replace(name)
}

// target 给会话名加 '=' 前缀。**tmux 的 -t 是前缀匹配**：`-t dev` 在没有 dev 时会挑中
// dev-review，于是「点开已经没了的 dev」静默连进了另一个会话，输入全打在别人身上。
// 这一条在 AGENTS.md 里写死了，本文件从前只有 exists() 遵守。
func target(name string) string { return "=" + name }

// paneTarget 是「这个会话当前窗口的活动 pane」。
//
// 那个尾冒号不是可有可无：tmux 3.4 下 `-t "=name"` 会被当成 **pane** 目标去解析，
// 直接 `can't find pane: =name`，于是 copy-mode / send-keys -X / display-message 的
// pane 变量全都静默失效——表现就是「终端翻不动页」：普通屏进不去 copy-mode，
// 备用屏那边 paneState 拿回一片空、alternate_on 判成 false，于是又走去 copy-mode。
// `=name` 只适合 has-session / set-option 这类会话级命令。
func paneTarget(name string) string { return "=" + name + ":" }

// sessionExists 判断会话是否真的还在（精确匹配，见 target）。
func sessionExists(name string) bool {
	return exec.Command("tmux", "has-session", "-t", target(name)).Run() == nil
}

// paneState 读活动 pane 的备用屏状态、鼠标上报模式与尺寸。
//   - alt=1：当前跑的是全屏 TUI（Claude Code / Codex / vim / less 等）。
//   - mouseOn：应用**真的**开了鼠标上报（任一模式）。这是能否给它合成滚轮的唯一可靠判据：
//     只看 alternate_on 是不够的，全屏但没开鼠标上报的应用（以及查询与发送之间刚退出备用屏的
//     shell）拿到裸序列不会消费，readline/输入框会把 ESC[< 之后的数字当普通字符吃进去，
//     表现就是命令行被 "65;137;33M65;137;33M…" 灌满、整屏花掉。
//   - sgr：应用用 SGR(1006) 扩展坐标编码；否则回退 X10 编码。
func paneState(name string) (alt, mouseOn, sgr bool, w, h int) {
	out, err := exec.Command("tmux", "display-message", "-p", "-t", paneTarget(name), "-F",
		"#{alternate_on} #{pane_width} #{pane_height} #{mouse_any_flag} #{mouse_standard_flag} #{mouse_button_flag} #{mouse_all_flag} #{mouse_sgr_flag}").Output()
	if err != nil {
		return false, false, false, 0, 0
	}
	parts := strings.Fields(strings.TrimSpace(string(out)))
	if len(parts) != 8 {
		return false, false, false, 0, 0
	}
	w, _ = strconv.Atoi(parts[1])
	h, _ = strconv.Atoi(parts[2])
	mouseOn = parts[3] == "1" || parts[4] == "1" || parts[5] == "1" || parts[6] == "1"
	return parts[0] == "1", mouseOn, parts[7] == "1", w, h
}

// maxWheelNotches 单条用户滚动消息最多合成多少格滚轮。一次快速滑动会连发几十条 touchmove，
// 不设上限时应用要连续重绘几十屏；万一它中途退出鼠标模式，残余字节还会成片打进输入行。
// 「回到底部」是显式动作，不受此限。
const maxWheelNotches = 10

// altScreenWheel 给备用屏 TUI 合成滚轮序列并作为输入发给应用，让它滚自己的缓冲。
// 备用屏没有 tmux scrollback，copy-mode 滚不动；全屏 TUI（Claude/Codex）普遍开了鼠标上报，
// 直接喂滚轮字节即可。坐标取 pane 中心；wheel 只有按下(M)无释放。
// 调用前必须确认 mouseOn（见 paneState）——没开鼠标上报的应用会把这些字节当普通输入吃掉。
func altScreenWheel(name, dir string, notches, w, h int, sgr bool) {
	btn := 64 // wheel up
	if dir != "up" {
		btn = 65 // wheel down
	}
	col, row := w/2, h/2
	if col < 1 {
		col = 1
	}
	if row < 1 {
		row = 1
	}
	var seq string
	if sgr {
		seq = fmt.Sprintf("\x1b[<%d;%d;%dM", btn, col, row)
	} else {
		// X10 编码：ESC [ M 后跟三个 32 偏移的字节，坐标上限 223
		if col > 223 {
			col = 223
		}
		if row > 223 {
			row = 223
		}
		seq = fmt.Sprintf("\x1b[M%c%c%c", rune(32+btn), rune(32+col), rune(32+row))
	}
	_ = exec.Command("tmux", "send-keys", "-t", paneTarget(name), "-l", "--", strings.Repeat(seq, notches)).Run()
}

// tmuxScroll 滚动会话历史，返回本连接是否仍停在 tmux copy-mode（供 handler 决定真实键入前是否需退出）。
//   - 普通屏：走 tmux copy-mode 滚真实 scrollback（attach 全屏，xterm 本地缓冲为空）。
//   - 备用屏(全屏 TUI)：copy-mode 无效，改合成滚轮序列发给应用，让它滚自己的对话缓冲。
func tmuxScroll(name, dir string, lines int) (inCopyMode bool) {
	if lines <= 0 {
		lines = 1
	}
	if alt, mouseOn, sgr, w, h := paneState(name); alt {
		// 全屏但没开鼠标上报：合成的滚轮字节不会被消费，会当普通输入打进应用的输入行
		// （命令行被 "65;137;33M…" 灌满、整屏花掉）。这种情况宁可不滚。
		if !mouseOn {
			return false
		}
		switch dir {
		case "up", "down":
			if lines > maxWheelNotches {
				lines = maxWheelNotches
			}
			altScreenWheel(name, dir, lines, w, h, sgr)
		case "bottom":
			// 全屏 TUI 无统一「到底」键；连发若干次向下滚轮，应用会在底部自然钳住。
			altScreenWheel(name, "down", 200, w, h, sgr)
		}
		return false // 没进 tmux copy-mode
	}
	n := strconv.Itoa(lines)
	switch dir {
	case "up":
		_ = exec.Command("tmux", "copy-mode", "-t", paneTarget(name)).Run()
		_ = exec.Command("tmux", "send-keys", "-t", paneTarget(name), "-N", n, "-X", "scroll-up").Run()
		return true
	case "down":
		_ = exec.Command("tmux", "send-keys", "-t", paneTarget(name), "-N", n, "-X", "scroll-down").Run()
		return true
	case "bottom":
		_ = exec.Command("tmux", "send-keys", "-t", paneTarget(name), "-X", "cancel").Run() // 退出 copy-mode 回到最新
	}
	return false
}

// A scroll burst shares pane state so touch events do not each spawn tmux.
type wheelState struct {
	alt     bool
	mouseOn bool
	sgr     bool
	w, h    int
	at      time.Time
}

func (ws *wheelState) refresh(name string) {
	if time.Since(ws.at) < 300*time.Millisecond {
		return
	}
	ws.alt, ws.mouseOn, ws.sgr, ws.w, ws.h = paneState(name)
	ws.at = time.Now()
}

func tmuxScrollCached(name, dir string, lines int, ws *wheelState) (inCopyMode bool) {
	if dir == "bottom" || lines <= 0 {
		return tmuxScroll(name, dir, lines)
	}
	ws.refresh(name)
	if !ws.alt {
		return tmuxScroll(name, dir, lines)
	}
	if !ws.mouseOn {
		return false
	}
	if lines > maxWheelNotches {
		lines = maxWheelNotches
	}
	altScreenWheel(name, dir, lines, ws.w, ws.h, ws.sgr)
	return false
}

// tmuxSelectPaneAt 把前端点击的单元格坐标(col,row)映射到所在 pane 并激活它。
// 因为关掉了 tmux 鼠标模式（保住 xterm 本地拖选复制），点击切换 pane 失效；这里在前端
// 单击(非拖选)时按坐标补回「点哪个 pane 就切到哪个」。divider 上的点击不命中任何 pane → 忽略。
func tmuxSelectPaneAt(name string, col, row int) {
	if col < 0 || row < 0 {
		return
	}
	out, err := exec.Command("tmux", "list-panes", "-t", target(name), "-F", "#{pane_id}\t#{pane_left}\t#{pane_top}\t#{pane_width}\t#{pane_height}").Output()
	if err != nil {
		return
	}
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		parts := strings.Split(line, "\t")
		if len(parts) != 5 {
			continue
		}
		left, err1 := strconv.Atoi(parts[1])
		top, err2 := strconv.Atoi(parts[2])
		width, err3 := strconv.Atoi(parts[3])
		height, err4 := strconv.Atoi(parts[4])
		if err1 != nil || err2 != nil || err3 != nil || err4 != nil {
			continue
		}
		if col >= left && col < left+width && row >= top && row < top+height {
			_ = exec.Command("tmux", "select-pane", "-t", parts[0]).Run()
			return
		}
	}
}

// tmuxMoveCursorAt 把前端「单击/轻点」的窗口格子坐标翻译成方向键，移动点中 pane 里应用的
// 输入光标，对齐原生输入框「点哪光标到哪」的体验——镜像终端的光标在远端 TUI/shell 手里，
// 点击本身移不动，此前只能靠丝带/键盘上的方向键一格格挪。
//   - 备用屏(全屏 TUI：Claude Code/Codex/vim)：只发水平 ←/→，绝不发竖直 ↑/↓——TUI 输入框里
//     ↑/↓ 普遍绑了历史/滚动(上翻/下翻)，点按稍一偏行就会误触；竖直定位交键盘方向键。
//     竖直距离过远(>8 行)视为点在对话区/输出区（非输入行），整体忽略。
//   - 普通屏(shell readline)：↑/↓ 会翻命令历史，绝不能发；把竖直距离按 pane 宽折算成
//     字符数（折行的长命令 ←/→ 本就会跨行走），只发 ←/→，越过行首行尾由 readline 钳住。
//   - pane 处于 copy-mode 等模式时不动作（按键会被导航吃掉）。
func tmuxMoveCursorAt(name string, col, row int) {
	if col < 0 || row < 0 {
		return
	}
	out, err := exec.Command("tmux", "list-panes", "-t", target(name), "-F",
		"#{pane_id}\t#{pane_left}\t#{pane_top}\t#{pane_width}\t#{pane_height}\t#{alternate_on}\t#{cursor_x}\t#{cursor_y}\t#{pane_in_mode}").Output()
	if err != nil {
		return
	}
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		parts := strings.Split(line, "\t")
		if len(parts) != 9 {
			continue
		}
		nums := make([]int, 8)
		ok := true
		for i := 1; i < len(parts); i++ {
			n, err := strconv.Atoi(parts[i])
			if err != nil {
				ok = false
				break
			}
			nums[i-1] = n
		}
		if !ok {
			continue
		}
		left, top, width, height := nums[0], nums[1], nums[2], nums[3]
		alt, cx, cy, inMode := nums[4] == 1, nums[5], nums[6], nums[7] == 1
		if col < left || col >= left+width || row < top || row >= top+height {
			continue
		}
		if inMode {
			return
		}
		dx, dy := (col-left)-cx, (row-top)-cy
		if alt {
			// 备用屏只认光标所在那一行的点击：别的行是对话/输出区，点它只是想聚焦。
			// 原来 ±8 行内都发 →，而 Claude Code 把行尾的 → 和 Tab 一样当成「接受建议提示」
			// （interactive-mode 文档 Prompt suggestions 一节）——用户点一下窗口，
			// 输入框里灰色的建议就变成真实输入了。
			if dy != 0 {
				return
			}
			if dx > 0 {
				// 往右不越过这一行最后一个真实字符：建议提示是暗色/灰色渲染的，当空白算。
				// 光标已经停在真实文字末尾时什么都不发——那正是 → 会被当成接受的位置。
				last := lastRealCol(capturePaneRow(parts[0], cy))
				if cx+dx > last+1 {
					dx = last + 1 - cx
				}
				if dx <= 0 {
					return
				}
			}
			sendArrows(parts[0], 0, dx)
		} else {
			if dy > 3 || dy < -3 {
				return
			}
			sendArrows(parts[0], 0, dy*width+dx)
		}
		return
	}
}

// sendArrows 先竖直后水平发方向键。用 tmux 命名键(Up/Down/Left/Right)而非裸序列，
// 让 tmux 按应用的光标键模式(DECCKM)选 CSI/SS3 编码。
// capturePaneRow 取 pane 第 row 行（0 起）的内容，带 SGR 转义（-e），供 lastRealCol 判断。
func capturePaneRow(pane string, row int) string {
	out, err := exec.Command("tmux", "capture-pane", "-p", "-e", "-t", pane,
		"-S", strconv.Itoa(row), "-E", strconv.Itoa(row)).Output()
	if err != nil {
		return ""
	}
	return strings.TrimRight(string(out), "\n")
}

// lastRealCol 返回一行里最后一个「真实字符」所在的列（0 起），没有则 -1。
// 暗色（SGR 2）或灰色前景（90、38;5;8、38;5;232–250、38;2 三分量相等且 ≤ 0xa0）渲染的字符
// 当空白：TUI 的占位符 / 建议提示都长这样，把光标挪到它们后面等于替用户接受它们。
func lastRealCol(line string) int {
	col, last := 0, -1
	dim, gray := false, false
	for i := 0; i < len(line); {
		if line[i] == 0x1b && i+1 < len(line) && line[i+1] == '[' {
			j := i + 2
			for j < len(line) && (line[j] < 0x40 || line[j] > 0x7e) {
				j++
			}
			if j < len(line) && line[j] == 'm' {
				dim, gray = applySGR(line[i+2:j], dim, gray)
			}
			i = j + 1
			continue
		}
		r, size := utf8.DecodeRuneInString(line[i:])
		w := cellWidth(r)
		if r != ' ' && !dim && !gray && w > 0 {
			last = col + w - 1
		}
		col += w
		i += size
	}
	return last
}

// applySGR 按一段 SGR 参数更新「暗 / 灰」两个标志。只关心会把字渲染成占位色的那几个。
func applySGR(params string, dim, gray bool) (bool, bool) {
	if params == "" {
		return false, false
	}
	ps := strings.Split(params, ";")
	for i := 0; i < len(ps); i++ {
		n, err := strconv.Atoi(ps[i])
		if err != nil {
			continue
		}
		switch {
		case n == 0:
			dim, gray = false, false
		case n == 2:
			dim = true
		case n == 22:
			dim = false
		case n == 90:
			gray = true
		case n == 39, (n >= 30 && n <= 37), (n >= 91 && n <= 97):
			gray = false
		case n == 38 && i+1 < len(ps):
			if ps[i+1] == "5" && i+2 < len(ps) {
				c, _ := strconv.Atoi(ps[i+2])
				gray = c == 8 || (c >= 232 && c <= 250)
				i += 2
			} else if ps[i+1] == "2" && i+4 < len(ps) {
				r, _ := strconv.Atoi(ps[i+2])
				g, _ := strconv.Atoi(ps[i+3])
				b, _ := strconv.Atoi(ps[i+4])
				gray = r == g && g == b && r <= 0xa0
				i += 4
			}
		}
	}
	return dim, gray
}

// cellWidth 是终端里一个字符占几列：宽字符（CJK 等）2、组合标记 0、其余 1。
// 只用来算光标钳位，不追求 wcwidth 全表精确。
func cellWidth(r rune) int {
	switch {
	case r == 0:
		return 0
	case r < 0x300:
		return 1
	case r >= 0x300 && r <= 0x36f, r >= 0x200b && r <= 0x200f:
		return 0
	case r >= 0x1100 && r <= 0x115f, r >= 0x2e80 && r <= 0xa4cf, r >= 0xac00 && r <= 0xd7a3,
		r >= 0xf900 && r <= 0xfaff, r >= 0xfe30 && r <= 0xfe4f, r >= 0xff00 && r <= 0xff60,
		r >= 0xffe0 && r <= 0xffe6, r >= 0x1f300 && r <= 0x1f64f, r >= 0x1f900 && r <= 0x1f9ff,
		r >= 0x20000 && r <= 0x3fffd:
		return 2
	}
	return 1
}

func sendArrows(pane string, dy, dx int) {
	send := func(key string, n int) {
		if n > 0 {
			_ = exec.Command("tmux", "send-keys", "-t", pane, "-N", strconv.Itoa(n), key).Run()
		}
	}
	if dy > 0 {
		send("Down", dy)
	} else {
		send("Up", -dy)
	}
	if dx > 0 {
		send("Right", dx)
	} else {
		send("Left", -dx)
	}
}

var upgrader = websocket.Upgrader{
	ReadBufferSize:  4096,
	WriteBufferSize: 4096,
	// 同源校验：Origin 的 host 必须等于请求 Host（配合 SameSite Cookie 防跨站劫持）
	CheckOrigin: func(r *http.Request) bool {
		origin := r.Header.Get("Origin")
		if origin == "" {
			return true // 非浏览器客户端
		}
		i := strings.Index(origin, "://")
		if i < 0 {
			return false
		}
		return origin[i+3:] == r.Host
	},
}

// closeSessionGone 是「这个 tmux 会话不存在」的关闭码（4000–4999 归应用自己用）。
// 前端见到它就不再重连——重连一万次也变不出一个已经被 kill 的会话。
const closeSessionGone = 4404

// Handler 处理 /api/term/:name 的 WebSocket 升级与 PTY 桥接。
func Handler(c *gin.Context) {
	name := SanitizeSessionName(c.Param("name"))
	conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		return
	}
	defer conn.Close()

	// 会话不在 tmux 里，先问台账认不认得它。
	//
	// 认得且只是**被机器重启带走的** → 当场按台账重开一个壳（有对话 id 的顺带接回），
	// 然后照常 attach 下去。这就是「懒恢复」：开机什么都不建，点开哪个哪个才活过来。
	//
	// 台账也不认（或是被显式 kill 的、原目录没了）→ 才是真的没了，用 4404 关掉。
	// 从前这里一律 attach：tmux 打一行 "can't find session" 就退出 → pty EOF → 前端按
	// 「普通断线」1.2s 后重连 → 再来一遍，永远停在「连接中」。
	if !sessionExists(name) {
		revived, ok := reviveDormant(name)
		if !ok {
			_ = conn.WriteMessage(websocket.TextMessage, []byte("\r\n[会话已不存在: "+name+"]\r\n"))
			_ = conn.WriteMessage(websocket.CloseMessage,
				websocket.FormatCloseMessage(closeSessionGone, "session gone"))
			return
		}
		// 重开的是新 id 的会话（旧行保持 dead，靠 restored_from 溯源）。前端必须知道
		// 改叫什么了，否则标签、URL、后续的 /api/term/<旧名> 全对不上，下次刷新又是死链接。
		notice, _ := json.Marshal(struct {
			Type string `json:"type"`
			From string `json:"from"`
			To   string `json:"to"`
		}{Type: "revived", From: name, To: revived})
		_ = conn.WriteMessage(websocket.TextMessage, notice)
		name = revived
	}

	// 关闭 tmux 鼠标模式，保留浏览器/xterm 原生拖选复制体验。
	// Web 端需要点击切换 pane 时，会发送 select-pane 控制消息，由后端按点击坐标选择窗格。
	_ = exec.Command("tmux", "set-option", "-t", target(name), "mouse", "off").Run()

	// 窗口尺寸跟随「最近活跃的客户端」，而非被所有 attach 客户端里最小的那个限制。
	// 同一会话被多处 attach（网页多标签 / 手机+桌面 / CLI）时，默认会缩到最小客户端，
	// 表现为当前这个明明很宽却渲染成左侧窄条；latest + aggressive-resize 让在用的客户端尺寸生效。
	_ = exec.Command("tmux", "set-option", "-t", target(name), "window-size", "latest").Run()
	_ = exec.Command("tmux", "set-window-option", "-t", target(name), "aggressive-resize", "on").Run()
	// extended-keys always: 让 tmux 接受并透传 CSI u 修饰键序列（如 Shift+Enter = \x1b[13;2u），
	// 使 Claude Code / Codex 等 TUI 能区分 Enter(提交) 与 Shift+Enter(换行)。
	_ = exec.Command("tmux", "set-option", "-t", target(name), "extended-keys", "always").Run()

	// 新连接一律退出可能残留的 copy-mode：copy-mode 是会话级状态，会跨 attach/重连存活。
	// 上次滚动历史进了 copy-mode 后断线重连时，本连接的 inCopy 会重置为 false，但 tmux 仍停在
	// copy-mode，键入被导航键吃掉到不了 shell（表现为「要先按底才能输入」）。这里让新客户端
	// 一律从实时提示符开始。
	_ = exec.Command("tmux", "send-keys", "-t", paneTarget(name), "-X", "cancel").Run()

	cmd := exec.Command("tmux", "attach", "-t", target(name))
	cmd.Env = utf8Env(append(os.Environ(), "TERM=xterm-256color"))
	// 用客户端带来的尺寸建 pty（StartWithSize 在 c.Start 前就把窗口大小设好）：
	// 先 Start 再 Setsize 会让 tmux attach 按默认 80x24 画完首帧、随即因 SIGWINCH 整屏重画一次，
	// 表现为进会话时闪一下 + 窄屏 TUI 留折行垃圾。
	sz := &creackpty.Winsize{Rows: 30, Cols: 100}
	if r, err := strconv.Atoi(c.Query("rows")); err == nil && r >= minRows && r <= 500 {
		sz.Rows = uint16(r)
	}
	if cl, err := strconv.Atoi(c.Query("cols")); err == nil && cl >= minCols && cl <= 1000 {
		sz.Cols = uint16(cl)
	}
	ptmx, err := creackpty.StartWithSize(cmd, sz)
	if err != nil {
		conn.WriteMessage(websocket.TextMessage, []byte("\r\n[无法连接会话: "+name+"]\r\n"))
		return
	}
	defer func() {
		_ = ptmx.Close()
		_ = cmd.Process.Kill()
		_, _ = cmd.Process.Wait()
	}()
	lastSize := *sz
	// pty 输出和控制消息 pong 可能同时写 WebSocket。gorilla 只允许一个并发 writer，
	// 所有连接级写入必须从这个小闸门经过，否则后台恢复探测会偶发 concurrent write panic。
	var writeMu sync.Mutex
	writeMessage := func(messageType int, data []byte) error {
		writeMu.Lock()
		defer writeMu.Unlock()
		return conn.WriteMessage(messageType, data)
	}

	// pty → ws
	go func() {
		buf := make([]byte, 4096)
		for {
			n, err := ptmx.Read(buf)
			if n > 0 {
				if werr := writeMessage(websocket.BinaryMessage, buf[:n]); werr != nil {
					return
				}
			}
			if err != nil {
				_ = writeMessage(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""))
				conn.Close()
				return
			}
		}
	}()

	// 跟踪本连接是否处于 tmux copy-mode（向上滚动会进入）。一旦进入，键入会被 copy-mode
	// 当导航键吃掉、到不了 shell，且新输出不再跟随到底。所以真实键入前先退出 copy-mode，
	// 让任意按键都像真实终端那样跳回实时提示符。
	inCopy := false
	wheel := &wheelState{}

	// ws → pty（文本帧若为 resize 控制消息则调整窗口大小，否则当作键入）
	for {
		mt, data, err := conn.ReadMessage()
		if err != nil {
			return
		}
		if mt == websocket.TextMessage && len(data) > 0 && data[0] == '{' {
			var ctrl struct {
				Type  string `json:"type"`
				Cols  uint16 `json:"cols"`
				Rows  uint16 `json:"rows"`
				Dir   string `json:"dir"`
				Lines int    `json:"lines"`
				Col   int    `json:"col"`
				Row   int    `json:"row"`
				ID    string `json:"id"`
			}
			if json.Unmarshal(data, &ctrl) == nil && ctrl.Type != "" {
				switch ctrl.Type {
				case "ping":
					// 浏览器从长时间后台恢复时先探测连接，不再无条件 close 全部终端。
					// pong 只证明这条 WS/PTY 桥仍可双向通信，不触碰 tmux 尺寸和屏幕内容。
					pong, _ := json.Marshal(struct {
						Type string `json:"type"`
						ID   string `json:"id"`
					}{Type: "pong", ID: ctrl.ID})
					if err := writeMessage(websocket.TextMessage, pong); err != nil {
						return
					}
					continue
				case "resize":
					// 防御异常尺寸：前端布局未就绪 / 面板折叠 / 离屏挂载时可能发来极窄的 cols(如 2)。
					// 因 window-size=latest，这会把共享会话挤成「窄条」，且客户端断开后仍卡住——
					// swarm 的 leader/成员会话(claude/codex TUI)会因此渲染崩坏，连 @leader 的消息都进不了输入框。
					// 低于阈值视为无效，忽略本次 resize（保持原尺寸，不被挤窄）。
					if ctrl.Cols < minCols || ctrl.Rows < minRows {
						continue
					}
					// 尺寸没变就不动：Setsize 会发 SIGWINCH，tmux 收到即整屏重排重绘。手机上
					// 软键盘/地址栏/旋转会连发同一尺寸，逐条照做就是用户看到的持续闪烁。
					if ctrl.Cols == lastSize.Cols && ctrl.Rows == lastSize.Rows {
						continue
					}
					lastSize = creackpty.Winsize{Rows: ctrl.Rows, Cols: ctrl.Cols}
					_ = creackpty.Setsize(ptmx, &lastSize)
					continue
				case "scroll":
					// 普通屏走 copy-mode 才需在真实键入前退出；备用屏 TUI 喂的是滚轮，inCopyMode=false。
					inCopy = tmuxScrollCached(name, ctrl.Dir, ctrl.Lines, wheel)
					continue
				case "select-pane":
					tmuxSelectPaneAt(name, ctrl.Col, ctrl.Row)
					continue
				case "move-cursor":
					// 若 pane 停在 copy-mode(含本连接滚动进入的)，内部会跳过，不打断浏览历史。
					tmuxMoveCursorAt(name, ctrl.Col, ctrl.Row)
					continue
				}
			}
		}
		// 有真实键入：若还停在 copy-mode，先退出回到底部，否则按键会被吃掉、打不到 shell。
		if inCopy {
			tmuxScroll(name, "bottom", 0)
			inCopy = false
		}
		if _, err := ptmx.Write(data); err != nil {
			return
		}
	}
}
