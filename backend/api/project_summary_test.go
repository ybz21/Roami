package api

import "testing"

// Top 被截到三行，所以它算不出总数。一个项目有 3 个运行中、2 个等待输入的会话时，
// 那两条**不能**从计数和「需要你」队列里消失——这是 #186 合并后前端拿 Top 数数留下的账。
func TestSummarizeSessionsCountsBeyondTop(t *testing.T) {
	top := []projectSession{
		{Name: "a", Running: true, Attached: true, LastActivity: 500},
		{Name: "b", Running: true, LastActivity: 400},
		{Name: "c", Running: true, LastActivity: 300},
		{Name: "d", Waiting: true, LastActivity: 200, Tail: "proceed? (y/n)"},
		{Name: "e", Waiting: true, LastActivity: 100},
	}
	var p projectSummary
	summarizeSessions(&p, top)

	if p.Running != 3 {
		t.Errorf("running = %d，期望 3（全量，不是 Top 里的三条）", p.Running)
	}
	if p.Waiting != 2 {
		t.Errorf("waiting = %d，期望 2——第 4/5 个会话的等待被漏掉了", p.Waiting)
	}
	if len(p.Needs) != 2 {
		t.Fatalf("needs = %d 条，期望 2 条（行动队列要的是全部等待会话）", len(p.Needs))
	}
	if p.Needs[0].Name != "d" || p.Needs[0].Tail == "" {
		t.Errorf("needs 应按活跃度倒序且带摘要，实际 %+v", p.Needs[0])
	}
	if len(p.Top) != 3 {
		t.Fatalf("top 应仍是三行，实际 %d", len(p.Top))
	}
	// 卡片只画三行，「有人在等你」是这三行里最该被看见的
	if !p.Top[0].Waiting || !p.Top[1].Waiting {
		t.Errorf("等待输入的会话应排在 Top 最前，实际 %v/%v", p.Top[0].Name, p.Top[1].Name)
	}
}

// 会话不足三条时不该凭空造出东西，计数也要对得上。
func TestSummarizeSessionsSmall(t *testing.T) {
	var p projectSummary
	summarizeSessions(&p, []projectSession{{Name: "a", Attached: true, LastActivity: 9}})
	if p.Running != 0 || p.Waiting != 0 || len(p.Needs) != 0 || len(p.Top) != 1 {
		t.Errorf("单会话汇总不对: running=%d waiting=%d needs=%d top=%d", p.Running, p.Waiting, len(p.Needs), len(p.Top))
	}
}
