package main

import (
	"strings"

	clihelp "github.com/ybz21/Roami/internal/cli/help"
)

func terminalCommandPage(name string) clihelp.Page {
	p := guidePage(name)
	var rows []clihelp.Entry
	if strings.HasPrefix(name, "plugin ") {
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
