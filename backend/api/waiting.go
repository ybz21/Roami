package api

import (
	"os/exec"
	"regexp"
	"strconv"
	"strings"
)

// 移植前端 prompt.tsx 的 detectPrompt 布尔判定：从一屏 capture 纯文本里看是否有
// 等待用户输入的交互框（Claude/Codex 的权限确认 / 编号选择菜单 / y-n）。列表绿点
// 语义（设计 W2）里的「黄=待输入」用它，务必与前端解析口径一致，避免列表/详情打架。
var (
	waitANSI         = regexp.MustCompile("\x1b\\[[0-?]*[ -/]*[@-~]")
	waitCtrl         = regexp.MustCompile("[\x00-\x08\x0b-\x1f\x7f]")
	waitCursorPrefix = regexp.MustCompile(`^[❯➤▶►▸→›»☞◉●>]\s*`)
	waitLead         = regexp.MustCompile(`^[\s│┃|╎┆┊╭╰├╞┝─━═]+`)
	waitTail         = regexp.MustCompile(`[\s│┃|╎┆┊╮╯┤╡┥─━═]+$`)
	waitOpt          = regexp.MustCompile(`^(?:[❯➤▶►▸→›»☞◉●>]\s*)?(\d+)[.)]\s+(\S.*)$`)
	waitQuestion     = regexp.MustCompile(`(?i)(would you like|do you want|are you sure|should (we|i)|(proceed|allow|continue|overwrite|approve|trust).*[?？]|是否(继续|允许|确认|执行)|(继续|允许|确认|执行).*[?？])`)
	waitAction       = regexp.MustCompile(`(?i)((enter|return).*(select|confirm|continue|submit|accept)|(esc|escape).*(cancel|back)|(回车|enter).*(选择|确认|继续)|(按|press).*(y|n|yes|no).*(确认|confirm))`)
	waitYesNo        = regexp.MustCompile(`(?i)\((?:y/n|yes/no)\)|\[y/n\]`)
)

func waitStripCtl(s string) string {
	return waitCtrl.ReplaceAllString(waitANSI.ReplaceAllString(s, ""), "")
}

func waitClean(s string) string {
	s = waitStripCtl(s)
	s = waitLead.ReplaceAllString(s, "")
	s = waitTail.ReplaceAllString(s, "")
	return strings.TrimSpace(s)
}

// sessionCapture 抓会话当前屏纯文本（=name 精确匹配，避开 tmux -t 前缀匹配 footgun）。
func sessionCapture(name string, lines int) string {
	// `=name:`：pane 类命令对裸 `=name` 报 can't find pane（tmux 3.4），带冒号才按「该会话当前窗口」解析
	out, err := exec.Command("tmux", "capture-pane", "-t", "="+name+":", "-p", "-J", "-S", "-"+strconv.Itoa(lines)).Output()
	if err != nil {
		return ""
	}
	return string(out)
}

// sessionTail 取一屏 capture 里最后一行有内容的输出，给「等待输入」行动卡当摘要。
// 与 sessionWaiting 吃同一份 capture——判待输入本来就抓了屏，不为摘要再抓一次。
func sessionTail(capture string, max int) string {
	lines := strings.Split(strings.ReplaceAll(waitStripCtl(capture), "\r", ""), "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		if s := waitClean(lines[i]); s != "" {
			if r := []rune(s); len(r) > max {
				return string(r[:max])
			}
			return s
		}
	}
	return ""
}

// sessionWaiting 判断一屏 capture 是否有等待输入的交互框（detectPrompt 的布尔版）。
func sessionWaiting(capture string) bool {
	lines := strings.Split(strings.ReplaceAll(waitStripCtl(capture), "\r", ""), "\n")
	type opt struct {
		num, idx int
		selected bool
	}
	var opts []opt
	for idx, raw := range lines {
		if m := waitOpt.FindStringSubmatch(waitClean(raw)); m != nil {
			n, _ := strconv.Atoi(m[1])
			opts = append(opts, opt{num: n, idx: idx, selected: waitCursorPrefix.MatchString(waitClean(raw))})
		}
	}
	// 取最后一组连续编号选项。窄屏下单个选项可能折成多行，与前端统一放宽到 ≤12 行。
	var g []opt
	for i := len(opts) - 1; i >= 0; i-- {
		if len(g) == 0 || g[0].idx-opts[i].idx <= 12 {
			g = append([]opt{opts[i]}, g...)
		} else {
			break
		}
	}
	// 必须从 1 起连续编号、至少两项，否则当普通编号列表不误判
	sequential := len(g) >= 2
	for k, o := range g {
		if o.num != k+1 {
			sequential = false
			break
		}
	}
	if sequential {
		var qlines []string
		for i := g[0].idx - 1; i >= 0 && g[0].idx-i <= 6; i-- {
			c := waitClean(lines[i])
			if c == "" {
				if len(qlines) > 0 {
					break
				}
				continue
			}
			if waitOpt.MatchString(c) {
				continue
			}
			qlines = append([]string{c}, qlines...)
			if len(qlines) >= 3 {
				break
			}
		}
		question := strings.TrimSpace(strings.Join(qlines, " "))
		lo := g[0].idx - 8
		if lo < 0 {
			lo = 0
		}
		hi := g[len(g)-1].idx + 3
		if hi > len(lines) {
			hi = len(lines)
		}
		var win []string
		for _, l := range lines[lo:hi] {
			win = append(win, waitClean(l))
		}
		windowText := strings.Join(win, " ")
		selectedCount := 0
		for _, o := range g {
			if o.selected {
				selectedCount++
			}
		}
		if selectedCount == 1 || (waitQuestion.MatchString(question) && waitAction.MatchString(windowText)) {
			return true
		}
	}
	// y/n 兜底
	for i := len(lines) - 1; i >= 0 && len(lines)-i <= 12; i-- {
		line := waitClean(lines[i])
		if line == "" {
			continue
		}
		if waitYesNo.MatchString(line) {
			return true
		}
		break
	}
	return false
}
