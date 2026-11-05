package swarm

import (
	"context"
	"fmt"
	"io"
	"net/url"
	"regexp"
)

var memberID = regexp.MustCompile(`^[a-f0-9]{32}$`)

func inspectMember(ctx context.Context, client *runtimeClient, path string, options commandOptions, w io.Writer, jsonOutput bool) error {
	id := options.args[1]
	if !memberID.MatchString(id) {
		return fmt.Errorf("persistent member ID required")
	}
	query := url.Values{}
	for _, name := range []string{"before", "limit"} {
		if options.value(name) == "" {
			continue
		}
		number, err := options.positive(name)
		if err != nil {
			return err
		}
		if name == "limit" && number > 50 {
			return fmt.Errorf("--limit must be 1..50")
		}
		query.Set(name, fmt.Sprint(number))
	}
	endpoint := path + "/members/" + url.PathEscape(id)
	if len(query) > 0 {
		endpoint += "?" + query.Encode()
	}
	raw, err := client.request(ctx, "GET", endpoint, nil)
	if err != nil {
		return err
	}
	if jsonOutput {
		return writeJSON(w, raw)
	}
	var value struct {
		Member member `json:"member"`
		Rounds struct {
			Items []struct {
				TaskID            string `json:"task_id"`
				Revision          int    `json:"revision"`
				State             string `json:"state"`
				Request           string `json:"request_text"`
				SourceUnavailable bool   `json:"sourceUnavailable"`
			} `json:"items"`
			NextBefore int64 `json:"nextBefore"`
		} `json:"rounds"`
	}
	if err = responseData(raw, &value); err != nil {
		return err
	}
	fmt.Fprintf(w, "%s  %s\nID: %s\n%s\n", line(value.Member.Name), stateLabel(value.Member.State), value.Member.ID, line(value.Member.Duty))
	for _, round := range value.Rounds.Items {
		request := line(round.Request)
		if round.SourceUnavailable {
			request = "来源消息不可用"
		} else if request == "" {
			request = "历史请求未记录"
		}
		fmt.Fprintf(w, "\n%s @%d  %s\n%s\n", round.TaskID, round.Revision, stateLabel(round.State), request)
	}
	if value.Rounds.NextBefore > 0 {
		fmt.Fprintf(w, "\n--before %d\n", value.Rounds.NextBefore)
	}
	return nil
}
