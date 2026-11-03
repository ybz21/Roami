package swarm

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/url"
	"sort"
	"strings"
	"text/tabwriter"
)

func stateLabel(state string) string {
	labels := map[string]string{"planning": "规划中", "queued": "待派发", "preparing": "准备中", "running": "执行中", "verifying": "待验收", "waiting_user": "需要输入", "review": "待审", "blocked": "受阻", "failed": "失败", "succeeded": "已验收", "done": "已完成", "unknown": "结果未知", "cancelled": "已取消", "interrupted": "已中断", "cancelling": "停止中", "idle": "空闲", "completed": "已结束"}
	if label, ok := labels[state]; ok {
		return label
	}
	return state
}
func line(value string) string { return strings.Join(strings.Fields(value), " ") }
func executorLabel(value string) string {
	if value == "native" {
		return "Roami"
	}
	return value
}
func renderDirectory(w io.Writer, values []snapshot, archived bool) error {
	table := tabwriter.NewWriter(w, 0, 4, 2, ' ', 0)
	fmt.Fprintln(table, "ID\t名称\t状态\t成员\t修订")
	for _, value := range values {
		if value.Archived != archived {
			continue
		}
		state := stateLabel(value.State)
		if value.Paused {
			state += " / 已暂停派发"
		}
		if value.Archived {
			state += " / 已归档"
		}
		fmt.Fprintf(table, "%s\t%s\t%s\t%d\t%d\n", value.ID, line(value.Name), state, len(value.Work), value.Revision)
	}
	return table.Flush()
}
func renderStatus(w io.Writer, value snapshot) error {
	fmt.Fprintf(w, "%s  %s\nID: %s\nMain: %s (%s)\n计划修订: %d\n", line(value.Name), stateLabel(value.State), value.ID, value.MainConversationID, stateLabel(value.MainState), value.Revision)
	if value.Paused {
		fmt.Fprintln(w, "已暂停派发")
	}
	if value.Archived {
		fmt.Fprintln(w, "已归档")
	}
	counts := map[string]int{}
	for _, work := range value.Work {
		counts[boardColumn(work.State)]++
	}
	for _, column := range []string{"backlog", "doing", "blocked", "review", "done"} {
		if counts[column] > 0 {
			fmt.Fprintf(w, "%s: %d  ", columnLabel(column), counts[column])
		}
	}
	_, err := fmt.Fprintln(w)
	return err
}
func renderMembers(w io.Writer, value snapshot) error {
	table := tabwriter.NewWriter(w, 0, 4, 2, ' ', 0)
	fmt.Fprintln(table, "工作项\t成员\t执行器\t状态\t任务修订\t任务\t会话")
	for _, work := range value.Work {
		session := ""
		if work.Attempt != nil {
			session = work.Attempt.SessionID
		}
		revision := "-"
		if work.Revision > 0 {
			revision = fmt.Sprint(work.Revision)
		}
		fmt.Fprintf(table, "%s\t%s\t%s\t%s\t%s\t%s\t%s\n", work.ID, line(work.Member), executorLabel(work.Executor), stateLabel(work.State), revision, work.TaskID, session)
	}
	return table.Flush()
}
func columnLabel(column string) string {
	return map[string]string{"backlog": "待办", "doing": "进行", "blocked": "受阻", "review": "待审", "done": "完成"}[column]
}
func renderBoard(w io.Writer, value snapshot) error {
	var output strings.Builder
	for _, column := range []string{"backlog", "doing", "blocked", "review", "done"} {
		fmt.Fprintf(&output, "\n[%s]\n", columnLabel(column))
		for _, work := range value.Work {
			if boardColumn(work.State) == column {
				fmt.Fprintf(&output, "  %s  %s  %s  %s\n", work.ID, line(work.Member), stateLabel(work.State), line(work.Title))
				if work.DispatchError != "" {
					fmt.Fprintf(&output, "    %s\n", work.DispatchError)
				}
			}
		}
	}
	_, err := io.WriteString(w, output.String())
	return err
}

func boardView(value snapshot) map[string]any {
	columns := map[string][]workItem{}
	for _, column := range []string{"backlog", "doing", "blocked", "review", "done"} {
		columns[column] = []workItem{}
	}
	for _, work := range value.Work {
		column := boardColumn(work.State)
		columns[column] = append(columns[column], work)
	}
	return map[string]any{"id": value.ID, "state": value.State, "revision": value.Revision, "columns": columns}
}
func renderSnapshot(w io.Writer, value snapshot, command string, jsonOutput bool) error {
	switch command {
	case "board":
		return renderBoard(w, value)
	case "members":
		return renderMembers(w, value)
	case "collect":
		verified := []workItem{}
		pending := []workItem{}
		for _, work := range value.Work {
			if work.State == "succeeded" {
				verified = append(verified, work)
			} else {
				pending = append(pending, work)
			}
		}
		if jsonOutput {
			return writeJSON(w, map[string]any{"data": map[string]any{"id": value.ID, "state": value.State, "verified": verified, "pending": pending}})
		}
		fmt.Fprintf(w, "已验收: %d / %d\n", len(verified), len(value.Work))
		for _, work := range verified {
			fmt.Fprintf(w, "\n%s (%s)\n任务: %s\n", line(work.Title), line(work.Member), work.TaskID)
			if work.Attempt != nil {
				fmt.Fprintln(w, work.Attempt.Summary)
			}
		}
		if len(pending) > 0 {
			fmt.Fprintln(w, "\n未完成:")
			for _, work := range pending {
				fmt.Fprintf(w, "  %s  %s\n", line(work.Member), stateLabel(work.State))
			}
		}
		return nil
	case "show":
		if err := renderStatus(w, value); err != nil {
			return err
		}
		fmt.Fprintf(w, "\n%s\n\n", value.Goal)
		return renderMembers(w, value)
	default:
		return renderStatus(w, value)
	}
}
func showWork(ctx context.Context, client *runtimeClient, value snapshot, selector string, w io.Writer, jsonOutput bool) error {
	work, err := findWork(value, selector)
	if err != nil {
		return err
	}
	var task any
	if work.TaskID != "" {
		raw, err := client.request(ctx, "GET", "/v1/tasks/"+url.PathEscape(work.TaskID), nil)
		if err != nil {
			return err
		}
		if err = responseData(raw, &task); err != nil {
			return err
		}
	}
	if jsonOutput {
		return writeJSON(w, map[string]any{"data": map[string]any{"work": work, "task": task}})
	}
	fmt.Fprintf(w, "%s  %s\n成员: %s (%s)\n工作项: %s\n任务: %s\n任务修订: %d\n\n目标\n%s\n\n验收标准\n%s\n", line(work.Title), stateLabel(work.State), line(work.Member), executorLabel(work.Executor), work.ID, work.TaskID, work.Revision, work.Goal, work.Acceptance)
	if work.DispatchError != "" {
		fmt.Fprintf(w, "\n阻塞: %s\n", work.DispatchError)
	}
	if len(work.Dependencies) > 0 {
		fmt.Fprintln(w, "\n依赖:")
		for _, dep := range work.Dependencies {
			member := dep.UpstreamID
			for _, upstream := range value.Work {
				if upstream.ID == dep.UpstreamID {
					member = upstream.Member
				}
			}
			fmt.Fprintf(w, "  %s@%d %s\n", line(member), dep.Revision, dep.ArtifactID)
		}
	}
	if task != nil {
		fmt.Fprintln(w, "\n原任务详情（含当前结果、产物与执行记录）:")
		encoder := json.NewEncoder(w)
		encoder.SetIndent("", "  ")
		return encoder.Encode(task)
	}
	return nil
}
func renderReceipt(w io.Writer, raw json.RawMessage, jsonOutput bool) error {
	if jsonOutput {
		return writeJSON(w, raw)
	}
	var receipt map[string]any
	if err := responseData(raw, &receipt); err != nil {
		return err
	}
	keys := make([]string, 0, len(receipt))
	for key := range receipt {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		value := receipt[key]
		switch value.(type) {
		case string, float64, bool, nil:
			fmt.Fprintf(w, "%s: %v\n", key, value)
		default:
			encoded, _ := json.Marshal(value)
			fmt.Fprintf(w, "%s: %s\n", key, encoded)
		}
	}
	return nil
}
