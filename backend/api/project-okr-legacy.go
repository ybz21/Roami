package api

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/okr"
	"golang.org/x/sys/unix"
)

var legacySwarmID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`)

type legacySwarmMember struct {
	Name    string `json:"name"`
	Type    string `json:"type"`
	Task    string `json:"task"`
	Status  string `json:"status"`
	Done    bool   `json:"done"`
	Pending bool   `json:"pending"`
	Kind    string `json:"kind"`
	Role    string `json:"role"`
	Subrole string `json:"subrole"`
	Duty    string `json:"duty"`
	Session string `json:"session"`
	Deps    string `json:"deps"`
}

type legacySwarmTask struct {
	ID           string `json:"id"`
	Title        string `json:"title"`
	Description  string `json:"description"`
	Assignee     string `json:"assignee"`
	Status       string `json:"status"`
	Dependencies string `json:"dependencies"`
	CreatedAt    string `json:"createdAt"`
	UpdatedAt    string `json:"updatedAt"`
}

type legacySwarmPost struct {
	ID        int64  `json:"id"`
	CreatedAt string `json:"createdAt"`
	Author    string `json:"author"`
	Kind      string `json:"kind"`
	ReplyTo   *int64 `json:"replyTo,omitempty"`
	Text      string `json:"text"`
}

type legacySwarmHistory struct {
	ID                 string              `json:"id"`
	Name               string              `json:"name"`
	Goal               string              `json:"goal"`
	Status             string              `json:"status"`
	Source             string              `json:"source"`
	Historical         bool                `json:"historical"`
	Verified           bool                `json:"verified"`
	Members            []legacySwarmMember `json:"members"`
	Tasks              []legacySwarmTask   `json:"tasks"`
	Posts              []legacySwarmPost   `json:"posts"`
	Truncated          map[string]bool     `json:"truncated"`
	UnavailableSources []string            `json:"unavailableSources"`
}

func (a *API) ProjectOKRLegacySwarm(c *gin.Context) {
	projectID, ok := a.okrProject(c)
	if !ok {
		return
	}
	var config *okr.Config
	var err error
	if reader, ok := any(a.ProjectOKR).(interface {
		ConfigReadOnly(string) (*okr.Config, error)
	}); ok {
		config, err = reader.ConfigReadOnly(projectID)
	} else {
		var workspace *okr.Workspace
		workspace, err = a.ProjectOKR.Get(projectID)
		if workspace != nil {
			config = &workspace.Config
		}
	}
	if err != nil {
		okrError(c, err)
		return
	}
	if config == nil || config.Swarm == "" {
		c.JSON(http.StatusOK, gin.H{"data": nil})
		return
	}
	if !a.Meta.OK() {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "OKR_HISTORY_UNAVAILABLE"})
		return
	}
	project, _ := a.Projects.Entry(projectID)
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()
	var history legacySwarmHistory
	var dir string
	err = a.Meta.SQL().QueryRowContext(ctx, `SELECT id,IFNULL(name,''),IFNULL(goal,''),IFNULL(status,''),IFNULL(dir,'') FROM swarms WHERE id=? OR name=? LIMIT 1`, config.Swarm, config.Swarm).Scan(&history.ID, &history.Name, &history.Goal, &history.Status, &dir)
	if errors.Is(err, sql.ErrNoRows) {
		c.JSON(http.StatusOK, gin.H{"data": nil})
		return
	}
	if err != nil {
		okrError(c, err)
		return
	}
	if !legacySwarmID.MatchString(history.ID) || !filepath.IsAbs(dir) || filepath.Clean(dir) != filepath.Clean(project.Dir) {
		c.JSON(http.StatusOK, gin.H{"data": nil})
		return
	}
	history.Source = "legacy"
	history.Historical = true
	history.Members = []legacySwarmMember{}
	history.Tasks = []legacySwarmTask{}
	history.Posts = []legacySwarmPost{}
	history.Truncated = map[string]bool{"members": false, "tasks": false, "posts": false}
	history.UnavailableSources = []string{}
	if err := readLegacyMembers(ctx, a.Meta.SQL(), "swarm_members", history.ID, &history); err != nil {
		okrError(c, err)
		return
	}
	if err := readLegacyTasks(ctx, a.Meta.SQL(), "swarm_cards", history.ID, &history); err != nil {
		okrError(c, err)
		return
	}
	// The migrated core ledger owns members/cards; legacy group databases retain posts.
	group, closeGroup, err := openLegacyGroup(a.Meta.Info().Path, history.ID)
	if err != nil {
		history.UnavailableSources = append(history.UnavailableSources, "posts")
	} else {
		defer closeGroup()
		if len(history.Members) == 0 {
			if err := readLegacyMembers(ctx, group, "members", "", &history); err != nil {
				history.UnavailableSources = append(history.UnavailableSources, "members")
			}
		}
		if len(history.Tasks) == 0 {
			if err := readLegacyTasks(ctx, group, "cards", "", &history); err != nil {
				history.UnavailableSources = append(history.UnavailableSources, "tasks")
			}
		}
		if err := readLegacyPosts(ctx, group, &history); err != nil {
			history.UnavailableSources = append(history.UnavailableSources, "posts")
		}
	}
	c.JSON(http.StatusOK, gin.H{"data": history})
}

func legacyColumns(ctx context.Context, db *sql.DB, table string) (map[string]bool, error) {
	rows, err := db.QueryContext(ctx, "PRAGMA table_info("+table+")")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	columns := map[string]bool{}
	for rows.Next() {
		var position, notnull, primary int
		var name, kind string
		var defaultValue any
		if err := rows.Scan(&position, &name, &kind, &notnull, &defaultValue, &primary); err != nil {
			return nil, err
		}
		columns[name] = true
	}
	return columns, rows.Err()
}

// Column names and table names come only from this file's fixed legacy schema allowlist.
func legacySelect(columns map[string]bool, names []string, numeric map[string]bool) string {
	expressions := make([]string, 0, len(names))
	for _, name := range names {
		if !columns[name] {
			if numeric[name] {
				expressions = append(expressions, "0")
			} else {
				expressions = append(expressions, "''")
			}
			continue
		}
		if numeric[name] {
			expressions = append(expressions, "IFNULL("+name+",0)")
		} else {
			expressions = append(expressions, "substr(IFNULL("+name+",''),1,16384)")
		}
	}
	return strings.Join(expressions, ",")
}

func readLegacyMembers(ctx context.Context, db *sql.DB, table, swarmID string, h *legacySwarmHistory) error {
	columns, err := legacyColumns(ctx, db, table)
	if err != nil {
		return err
	}
	if !columns["name"] {
		return nil
	}
	query := "SELECT " + legacySelect(columns, []string{"name", "type", "task", "status", "done", "pending", "kind", "role", "subrole", "duty", "session", "deps"}, map[string]bool{"done": true, "pending": true}) + " FROM " + table
	var args []any
	if swarmID != "" {
		query += " WHERE swarm_id=?"
		args = append(args, swarmID)
	}
	query += " ORDER BY name LIMIT 201"
	rows, err := db.QueryContext(ctx, query, args...)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var member legacySwarmMember
		var done, pending int
		if err := rows.Scan(&member.Name, &member.Type, &member.Task, &member.Status, &done, &pending, &member.Kind, &member.Role, &member.Subrole, &member.Duty, &member.Session, &member.Deps); err != nil {
			return err
		}
		member.Done = done != 0
		member.Pending = pending != 0
		h.Members = append(h.Members, member)
	}
	if len(h.Members) > 200 {
		h.Members = h.Members[:200]
		h.Truncated["members"] = true
	}
	return rows.Err()
}

func readLegacyTasks(ctx context.Context, db *sql.DB, table, swarmID string, h *legacySwarmHistory) error {
	columns, err := legacyColumns(ctx, db, table)
	if err != nil {
		return err
	}
	if !columns["id"] {
		return nil
	}
	query := "SELECT " + legacySelect(columns, []string{"id", "title", "descr", "assignee", "col", "deps", "created", "updated"}, nil) + " FROM " + table
	var args []any
	if swarmID != "" {
		query += " WHERE swarm_id=?"
		args = append(args, swarmID)
	}
	query += " ORDER BY id LIMIT 501"
	rows, err := db.QueryContext(ctx, query, args...)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var task legacySwarmTask
		if err := rows.Scan(&task.ID, &task.Title, &task.Description, &task.Assignee, &task.Status, &task.Dependencies, &task.CreatedAt, &task.UpdatedAt); err != nil {
			return err
		}
		h.Tasks = append(h.Tasks, task)
	}
	if len(h.Tasks) > 500 {
		h.Tasks = h.Tasks[:500]
		h.Truncated["tasks"] = true
	}
	return rows.Err()
}

func readLegacyPosts(ctx context.Context, db *sql.DB, h *legacySwarmHistory) error {
	columns, err := legacyColumns(ctx, db, "posts")
	if err != nil {
		return err
	}
	if !columns["id"] || !columns["text"] {
		return errors.New("legacy posts missing")
	}
	query := "SELECT " + legacySelect(columns, []string{"id", "ts", "author", "kind", "re", "text"}, map[string]bool{"id": true, "re": true}) + " FROM posts ORDER BY id DESC LIMIT 201"
	rows, err := db.QueryContext(ctx, query)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var post legacySwarmPost
		var reply int64
		if err := rows.Scan(&post.ID, &post.CreatedAt, &post.Author, &post.Kind, &reply, &post.Text); err != nil {
			return err
		}
		if reply != 0 {
			post.ReplyTo = &reply
		}
		h.Posts = append(h.Posts, post)
	}
	if len(h.Posts) > 200 {
		h.Posts = h.Posts[:200]
		h.Truncated["posts"] = true
	}
	sort.Slice(h.Posts, func(i, j int) bool { return h.Posts[i].ID < h.Posts[j].ID })
	return rows.Err()
}

func legacyRegular(root *os.Root, name string) (*os.File, error) {
	info, err := root.Lstat(name)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() {
		return nil, errors.New("unsafe legacy source")
	}
	file, err := root.OpenFile(name, os.O_RDONLY|unix.O_NOFOLLOW|unix.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	actual, err := file.Stat()
	if err != nil || !actual.Mode().IsRegular() {
		file.Close()
		if err != nil {
			return nil, err
		}
		return nil, errors.New("unsafe legacy source")
	}
	return file, nil
}

// Read a bounded private copy, including WAL, so SQLite never opens or writes live sidecars.
func openLegacyGroup(metaPath, swarmID string) (*sql.DB, func(), error) {
	if !filepath.IsAbs(metaPath) || !legacySwarmID.MatchString(swarmID) {
		return nil, nil, errors.New("invalid legacy source")
	}
	root, err := os.OpenRoot(filepath.Dir(metaPath))
	if err != nil {
		return nil, nil, err
	}
	defer root.Close()
	for _, name := range []string{"swarms", "swarms/" + swarmID} {
		info, err := root.Lstat(name)
		if err != nil {
			return nil, nil, err
		}
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return nil, nil, errors.New("unsafe legacy directory")
		}
	}
	group, err := root.OpenRoot("swarms/" + swarmID)
	if err != nil {
		return nil, nil, err
	}
	defer group.Close()
	temp, err := os.MkdirTemp("", "roami-legacy-history-")
	if err != nil {
		return nil, nil, err
	}
	cleanup := func() { _ = os.RemoveAll(temp) }
	type sourceFile struct {
		name   string
		file   *os.File
		before os.FileInfo
	}
	sources := []sourceFile{}
	defer func() {
		for _, source := range sources {
			_ = source.file.Close()
		}
	}()
	walMissing := false
	for _, name := range []string{"swarm.db", "swarm.db-wal"} {
		source, err := legacyRegular(group, name)
		if errors.Is(err, fs.ErrNotExist) && strings.HasSuffix(name, "-wal") {
			walMissing = true
			continue
		}
		if err != nil {
			cleanup()
			return nil, nil, err
		}
		info, err := source.Stat()
		if err != nil {
			source.Close()
			cleanup()
			return nil, nil, err
		}
		if info.Size() > 64<<20 {
			source.Close()
			cleanup()
			return nil, nil, errors.New("legacy source too large")
		}
		sources = append(sources, sourceFile{name, source, info})
	}
	for _, source := range sources {
		destination, err := os.OpenFile(filepath.Join(temp, source.name), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			cleanup()
			return nil, nil, err
		}
		copied, copyErr := io.Copy(destination, io.LimitReader(source.file, (64<<20)+1))
		closeErr := destination.Close()
		if copyErr != nil || closeErr != nil || copied != source.before.Size() {
			cleanup()
			return nil, nil, errors.New("legacy snapshot copy failed")
		}
	}
	for _, source := range sources {
		after, statErr := source.file.Stat()
		current, pathErr := group.Lstat(source.name)
		if statErr != nil || pathErr != nil || !os.SameFile(source.before, current) || after.Size() != source.before.Size() || !after.ModTime().Equal(source.before.ModTime()) {
			cleanup()
			return nil, nil, errors.New("legacy source changed while reading")
		}
	}
	if walMissing {
		if _, err := group.Lstat("swarm.db-wal"); !errors.Is(err, fs.ErrNotExist) {
			cleanup()
			return nil, nil, errors.New("legacy WAL changed while reading")
		}
	}
	uri := url.URL{Scheme: "file", Path: filepath.Join(temp, "swarm.db")}
	query := url.Values{"mode": {"ro"}, "_pragma": {"query_only(1)", "busy_timeout(1000)"}}
	uri.RawQuery = query.Encode()
	db, err := sql.Open("sqlite", uri.String())
	if err != nil {
		cleanup()
		return nil, nil, err
	}
	db.SetMaxOpenConns(1)
	if err := db.Ping(); err != nil {
		db.Close()
		cleanup()
		return nil, nil, fmt.Errorf("legacy snapshot: %w", err)
	}
	return db, func() { _ = db.Close(); cleanup() }, nil
}
