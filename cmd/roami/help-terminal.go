package main

import (
	"slices"
	"strings"

	clihelp "github.com/ybz21/Roami/internal/cli/help"
)

func terminalCommandPage(name string) clihelp.Page {
	p := guidePage(name)
	var rows []clihelp.Entry
	if strings.HasPrefix(name, "chrome ") {
		verb := strings.TrimPrefix(name, "chrome ")
		if verb == "setup" {
			p.Notes = append(p.Notes, "安装或更新 Node 与 playwright-core 依赖。")
			return p
		}
		if !slices.Contains([]string{"setup", "tabs", "capabilities", "new", "record stop", "record status", "operation-status", "operation-cancel"}, verb) {
			rows = append(rows, clihelp.Entry{Name: "--target TAB_ID", Description: "稳定标签页 ID；先用 tabs 查询"}, clihelp.Entry{Name: "--tab N / --url TEXT", Description: "也可按序号或 URL 子串选择；三种方式不混用"})
		}
		rows = append(rows, clihelp.Entry{Name: "--timeout MS", Description: "超时（默认 15000 毫秒；0 关闭操作超时）"}, clihelp.Entry{Name: "--cdp URL", Description: "指定 Chrome 调试地址；默认跟随 Roami 浏览器"}, clihelp.Entry{Name: "--no-start", Description: "只连接已有 Chrome"}, clihelp.Entry{Name: "--no-retry", Description: "只执行一次；未知结果不重放"})
		if verb == "screenshot" {
			rows = append(rows, clihelp.Entry{Name: "--full", Description: "截取完整页面"}, clihelp.Entry{Name: "--viewport WIDTHxHEIGHT", Description: "视口尺寸"}, clihelp.Entry{Name: "--wait MS", Description: "截图前等待时间"}, clihelp.Entry{Name: "--clip x,y,w,h", Description: "截图区域"}, clihelp.Entry{Name: "--fast", Description: "快速截图"}, clihelp.Entry{Name: "--fresh [--goto URL]", Description: "使用临时干净浏览器截图"}, clihelp.Entry{Name: "--quality N", Description: "JPEG 质量（1–100）"}, clihelp.Entry{Name: "--mobile / --device NAME", Description: "手机视口；机型 iphone、iphone-se、pixel、ipad"})
			p.Notes = append(p.Notes, "默认保存 screenshot.png；截图失败会尝试 CDP 路径，仍受超时约束。")
		}
		if verb == "upload" {
			rows = append(rows, clihelp.Entry{Name: "--file-root PATH", Description: "限定源文件目录"}, clihelp.Entry{Name: "--max-file-bytes N", Description: "限制文件大小"}, clihelp.Entry{Name: "--expected-file-sha256 SHA", Description: "核对源文件摘要"})
			p.Notes = append(p.Notes, "文件须小于 50 MiB；成功只表示文件已选入页面，仍需核对上传或提交结果。")
		}
		if verb == "goto" {
			rows = append(rows, clihelp.Entry{Name: "--wait-until STATE", Description: "等待 load、domcontentloaded 或 commit"})
		}
		if verb == "new" {
			rows = append(rows, clihelp.Entry{Name: "--origin human|agent", Description: "标签页归属；默认 agent"})
		}
		if verb == "observe" {
			rows = append(rows, clihelp.Entry{Name: "--screenshot PATH", Description: "同时保存页面截图"})
		}
		if verb == "sleep" {
			rows = append(rows, clihelp.Entry{Name: "--no-focus", Description: "只处理可安全保留状态的后台页"})
		}
		if verb == "close" {
			rows = append(rows, clihelp.Entry{Name: "--no-focus", Description: "不切换前台标签页"}, clihelp.Entry{Name: "--only-if-background", Description: "只关闭后台标签页"})
		}
		if strings.HasPrefix(verb, "record ") {
			p.Notes = append(p.Notes, "录制需要系统安装 ffmpeg。")
		}
		rows = append(rows, clihelp.Entry{Name: "--operation-id ID", Description: "持久化动作 ID（32 位）"}, clihelp.Entry{Name: "--receipt-root PATH", Description: "私有动作回执目录"}, clihelp.Entry{Name: "--expected-browser ID", Description: "动作前核对浏览器实例"}, clihelp.Entry{Name: "--expected-scene SIGNATURE", Description: "动作前核对页面观察签名"})
		p.Notes = append(p.Notes, "受管任务使用 --resource ID 观察，或用 --observation ID 执行动作；身份由当前 Agent 工具上下文提供。")
	} else if strings.HasPrefix(name, "plugin ") {
		g := commandGuides[name]
		for _, entry := range []clihelp.Entry{{Name: "PLUGIN_ID", Description: "插件 ID；先用 roami plugin ls 查询"}, {Name: "SESSION", Description: "稳定会话 ID"}, {Name: "--json", Description: "输出 JSON"}, {Name: "--removed", Description: "列出可恢复的已卸载内置插件"}, {Name: "--purge", Description: "同时删除配置与数据"}, {Name: "--label KEY=VALUE", Description: "插件跟踪标签，可重复"}, {Name: "--foreground", Description: "在前台运行"}} {
			key := strings.Fields(entry.Name)[0]
			if strings.Contains(g.syntax, key) {
				rows = append(rows, entry)
			}
		}
		if name == "plugin install" {
			p.Notes = append(p.Notes, "外部插件默认未启用；检查详情后使用 enable。")
		}
	}
	p.Sections = []clihelp.Section{{Title: "参数", Entries: rows}}
	return p
}
