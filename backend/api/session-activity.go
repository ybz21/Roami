package api

import (
	"crypto/sha256"
	"encoding/json"
	"strconv"
	"strings"

	"github.com/ybz21/Roami/internal/tmuxruntime"
)

type sessionPane struct {
	session, identity, id, dir string
	pid                        int
	activity, confirmedAt      int64
	width, height              int
	active                     bool
	agent                      agentProc
}

func scanSessionPanes(rt runtime.Runtime) []sessionPane {
	const format = "#{session_name}\t#{session_id}:#{session_created}\t#{pane_id}\t#{pane_pid}\t" +
		"#{window_activity}\t#{&&:#{window_active},#{pane_active}}\t#{pane_width}\t#{pane_height}\t#{pane_current_path}"
	out, err := rt.TmuxOutput("list-panes", "-a", "-F", format)
	if err != nil {
		return nil
	}
	var panes []sessionPane
	for _, line := range strings.Split(out, "\n") {
		parts := strings.SplitN(line, "\t", 9)
		if len(parts) != 9 {
			continue
		}
		pid, _ := strconv.Atoi(parts[3])
		activity, _ := strconv.ParseInt(parts[4], 10, 64)
		width, _ := strconv.Atoi(parts[6])
		height, _ := strconv.Atoi(parts[7])
		panes = append(panes, sessionPane{
			session: parts[0], identity: parts[1], id: parts[2], pid: pid,
			activity: activity, active: parts[5] == "1", width: width, height: height, dir: parts[8],
		})
	}
	return panes
}

type paneActivity struct {
	screen        [sha256.Size]byte
	observedAt    int64
	width, height int
}

type sessionActivity struct {
	identity  string
	at        int64
	confirmed bool
	panes     map[string]paneActivity
}

func (s sessionActivity) observe(row sessListItem, panes []sessionPane, now int64, capture func(string) (string, bool)) sessionActivity {
	identity := row.identity()
	if identity != s.identity {
		s = sessionActivity{identity: identity, at: row.activityBaseline()}
	}
	if identity == "" || row.dormant() || len(panes) == 0 {
		return s
	}

	next := make(map[string]paneActivity, len(panes))
	for _, pane := range panes {
		if usesTranscriptActivity(pane.agent.Kind) {
			s.confirm(pane.confirmedAt)
			continue
		}
		old, seen := s.panes[pane.id]
		if seen {
			next[pane.id] = old
			// tmux reports whole seconds. Recheck writes in the same second as the last capture.
			if pane.activity < old.observedAt {
				continue
			}
		}
		text, ok := capture(pane.id)
		if !ok {
			continue
		}
		// tmux advances window_activity on focus and on any PTY bytes, even an identical redraw.
		hash := paneActivityHash(text, pane.agent.Kind != "")
		next[pane.id] = paneActivity{screen: hash, observedAt: now, width: pane.width, height: pane.height}
		if seen && old.width == pane.width && old.height == pane.height && hash != old.screen {
			s.confirm(pane.activity)
		}
	}
	s.panes = next
	return s
}

func (s *sessionActivity) confirm(at int64) {
	if at > 0 && (!s.confirmed || at > s.at) {
		s.at, s.confirmed = at, true
	}
}

func paneActivityHash(text string, agent bool) [sha256.Size]byte {
	if agent {
		lines := strings.Split(text, "\n")
		content := lines[:0]
		for _, line := range lines {
			clean := waitClean(line)
			if chromeLine.MatchString(clean) || openCodeProgress.MatchString(clean) {
				continue
			}
			content = append(content, line)
		}
		text = strings.Join(content, "\n")
	}
	return sha256.Sum256([]byte(strings.Join(strings.Fields(text), " ")))
}

func (s sessListItem) identity() string {
	if s.TmuxID == "" || s.Created == "" {
		return ""
	}
	return s.TmuxID + ":" + s.Created
}

func (l *liveTable) sessionActivity(row sessListItem) int64 {
	if at, ok := l.observedActivity(row); ok {
		return at
	}
	return row.activityBaseline()
}

func (s sessListItem) activityBaseline() int64 {
	if !s.dormant() && s.identity() != "" {
		created, _ := strconv.ParseInt(s.Created, 10, 64)
		return created
	}
	return rawInt(s.LastActivity)
}

func (l *liveTable) observedActivity(row sessListItem) (int64, bool) {
	if identity := row.identity(); identity != "" && !row.dormant() {
		if snap, ok := l.get(row.Name); ok && snap.Activity.identity == identity && snap.Activity.at > 0 {
			return snap.Activity.at, true
		}
	}
	return 0, false
}

// Keep the CLI response fields and their types for both the flat list and the tree.
func (l *liveTable) projectSessionActivity(body []byte) []byte {
	var rows []json.RawMessage
	if err := json.Unmarshal(body, &rows); err != nil {
		return body
	}
	var visit func(json.RawMessage) json.RawMessage
	visit = func(raw json.RawMessage) json.RawMessage {
		var row struct {
			sessListItem
			Children []json.RawMessage `json:"children"`
		}
		if err := json.Unmarshal(raw, &row); err != nil {
			return raw
		}
		at := l.sessionActivity(row.sessListItem)
		changed := len(row.LastActivity) > 0 && at != rawInt(row.LastActivity)
		if !changed && len(row.Children) == 0 {
			return raw
		}
		var fields map[string]json.RawMessage
		if err := json.Unmarshal(raw, &fields); err != nil {
			return raw
		}
		if changed {
			value := strconv.FormatInt(at, 10)
			if len(row.LastActivity) > 0 && row.LastActivity[0] == '"' {
				value = strconv.Quote(value)
			}
			fields["last_activity"] = json.RawMessage(value)
		}
		if len(row.Children) > 0 {
			for i, child := range row.Children {
				row.Children[i] = visit(child)
			}
			children, _ := json.Marshal(row.Children)
			fields["children"] = children
		}
		result, err := json.Marshal(fields)
		if err != nil {
			return raw
		}
		return result
	}
	for i, row := range rows {
		rows[i] = visit(row)
	}
	result, err := json.Marshal(rows)
	if err != nil {
		return body
	}
	return result
}
