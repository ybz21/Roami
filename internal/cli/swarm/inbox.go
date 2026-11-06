package swarm

import (
	"context"
	"fmt"
	"io"
	"net/url"
)

func readInbox(ctx context.Context, client *runtimeClient, path string, options commandOptions, w io.Writer, jsonOutput bool) error {
	query := url.Values{}
	body := map[string]any{}
	for _, name := range []string{"before", "limit"} {
		if options.value(name) == "" {
			continue
		}
		number, err := options.positive(name)
		if err != nil {
			return err
		}
		if name == "limit" && number > 100 {
			return fmt.Errorf("--limit must be 1..100")
		}
		query.Set(name, fmt.Sprint(number))
		body[name] = number
	}
	method, endpoint := "GET", path+"/inbox"
	if options.value("task") != "" || options.value("run") != "" || options.value("task-revision") != "" {
		if options.value("member") != "" {
			return fmt.Errorf("--member cannot override a bound task recipient")
		}
		for _, field := range []struct{ flag, key string }{{"task", "taskId"}, {"run", "runId"}} {
			value, err := options.required(field.flag)
			if err != nil {
				return err
			}
			body[field.key] = value
		}
		revision, err := options.positive("task-revision")
		if err != nil {
			return err
		}
		body["taskRevision"] = revision
		method, endpoint = "POST", path+"/member-inbox"
	} else {
		if id := options.value("member"); id != "" {
			if !memberID.MatchString(id) {
				return fmt.Errorf("persistent member ID required")
			}
			query.Set("memberId", id)
		}
		if len(query) > 0 {
			endpoint += "?" + query.Encode()
		}
		body = nil
	}
	raw, err := client.request(ctx, method, endpoint, body)
	if err != nil {
		return err
	}
	if jsonOutput {
		return writeJSON(w, raw)
	}
	var value struct {
		Items []struct {
			PostID        int64  `json:"postId"`
			Author        string `json:"author"`
			Text          string `json:"text"`
			ReadMS        *int64 `json:"readMs"`
			SourceCurrent bool   `json:"sourceCurrent"`
		} `json:"items"`
		NextBefore *int64 `json:"nextBefore"`
	}
	if err = responseData(raw, &value); err != nil {
		return err
	}
	if len(value.Items) == 0 {
		_, err = fmt.Fprintln(w, "没有待处理消息")
		return err
	}
	for _, item := range value.Items {
		state := "待处理"
		if item.ReadMS != nil {
			state = "已获取，待答复"
		}
		if !item.SourceCurrent {
			state += " / 历史任务轮次"
		}
		if _, err = fmt.Fprintf(w, "\n%d %s / %s\n%s\n", item.PostID, line(item.Author), state, item.Text); err != nil {
			return err
		}
	}
	if value.NextBefore != nil {
		_, err = fmt.Fprintf(w, "\n--before %d\n", *value.NextBefore)
	}
	return err
}
