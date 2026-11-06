package okr

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"io/fs"
	"os"
	"path"
	"strings"
	"unicode/utf8"
)

const maxDashboardFile = 1 << 20
const maxDashboardBundle = 2 << 20

type HTMLDashboard struct {
	Entry     string   `json:"entry"`
	Assets    []string `json:"assets"`
	MetricIDs []string `json:"metricIds"`
	Libraries []string `json:"libraries,omitempty"`
}

type DashboardAsset struct {
	MIMEType string `json:"mimeType"`
	Body     []byte `json:"body"`
	SHA256   string `json:"sha256"`
}

type DashboardBundle struct {
	Digest    string                    `json:"digest"`
	Entry     string                    `json:"entry"`
	MetricIDs []string                  `json:"metricIds"`
	Libraries []string                  `json:"libraries"`
	Assets    map[string]DashboardAsset `json:"assets"`
}

func dashboardAssetMIME(name string) string {
	switch path.Ext(name) {
	case ".html":
		return "text/html"
	case ".css":
		return "text/css"
	case ".js":
		return "text/javascript"
	}
	return ""
}

func validDashboardPath(name string) bool {
	return fs.ValidPath(name) && strings.HasPrefix(name, "dashboard/") && !strings.ContainsAny(name, `\\:%?#`) && dashboardAssetMIME(name) != ""
}

func validateHTMLDashboard(html *HTMLDashboard, metrics map[string]bool) error {
	if !validDashboardPath(html.Entry) || path.Ext(html.Entry) != ".html" || len(html.Assets) == 0 || len(html.Assets) > 32 || len(html.MetricIDs) == 0 || len(html.MetricIDs) > 64 {
		return ErrInvalid
	}
	seen := map[string]bool{}
	for _, file := range html.Assets {
		if !validDashboardPath(file) || seen[file] {
			return ErrInvalid
		}
		seen[file] = true
	}
	if !seen[html.Entry] {
		return ErrInvalid
	}
	seen = map[string]bool{}
	for _, id := range html.MetricIDs {
		if !metrics[id] || seen[id] {
			return ErrInvalid
		}
		seen[id] = true
	}
	if len(html.Libraries) > 1 || len(html.Libraries) == 1 && html.Libraries[0] != "echarts" {
		return ErrInvalid
	}
	return nil
}

// Open the checked directory itself so later path changes cannot redirect reads to sibling project data.
func dashboardRoot(root *os.Root) (*os.Root, error) {
	before, err := root.Lstat("dashboard")
	if err != nil {
		return nil, err
	}
	if !before.IsDir() || before.Mode()&os.ModeSymlink != 0 {
		return nil, ErrInvalid
	}
	opened, err := root.OpenRoot("dashboard")
	if err != nil {
		return nil, err
	}
	after, err := opened.Stat(".")
	if err != nil || !os.SameFile(before, after) {
		opened.Close()
		return nil, ErrInvalid
	}
	return opened, nil
}

func dashboardDigest(bundle *DashboardBundle) (string, error) {
	canonical := *bundle
	canonical.Digest = ""
	body, err := json.Marshal(canonical)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(body)
	return hex.EncodeToString(digest[:]), nil
}

func captureDashboard(root *os.Root, definition *Dashboard) (*DashboardBundle, error) {
	if definition == nil || definition.HTML == nil {
		return nil, nil
	}
	html := definition.HTML
	dir, err := dashboardRoot(root)
	if err != nil {
		return nil, ErrInvalid
	}
	defer dir.Close()
	bundle := &DashboardBundle{Entry: html.Entry, MetricIDs: append([]string{}, html.MetricIDs...), Libraries: append([]string{}, html.Libraries...), Assets: map[string]DashboardAsset{}}
	total := 0
	for _, file := range html.Assets {
		body, err := readFile(dir, strings.TrimPrefix(file, "dashboard/"), maxDashboardFile)
		if err != nil || !utf8.Valid(body) {
			return nil, ErrInvalid
		}
		total += len(body)
		if total > maxDashboardBundle {
			return nil, ErrInvalid
		}
		digest := sha256.Sum256(body)
		bundle.Assets[file] = DashboardAsset{MIMEType: dashboardAssetMIME(file), Body: body, SHA256: hex.EncodeToString(digest[:])}
	}
	if err := validateDashboardMarkup(bundle); err != nil {
		return nil, err
	}
	bundle.Digest, err = dashboardDigest(bundle)
	return bundle, err
}

func persistDashboard(root *os.Root, bundle *DashboardBundle) error {
	name := "state/dashboard-assets/" + bundle.Digest + ".json"
	body, err := json.Marshal(bundle)
	if err != nil {
		return err
	}
	if _, err := root.Lstat(name); err == nil {
		previous, err := readFile(root, name, 4<<20)
		if err != nil {
			return err
		}
		if !bytes.Equal(previous, body) {
			return ErrInvalid
		}
		return nil
	} else if !os.IsNotExist(err) {
		return err
	}
	return atomicFile(root, name, body)
}

// Dashboard returns only the approved asset bundle, never the current working HTML or project instructions.
func (s *Store) Dashboard(projectID string) (*DashboardBundle, *Workspace, error) {
	if s.projects == nil {
		return nil, nil, ErrInvalid
	}
	root, err := s.openBundle(projectID, false)
	if os.IsNotExist(err) {
		return nil, nil, ErrNotFound
	}
	if err != nil {
		return nil, nil, err
	}
	defer root.Close()
	snapshot, err := loadSnapshot(root)
	if os.IsNotExist(err) {
		return nil, nil, ErrNotFound
	}
	if err != nil {
		return nil, nil, err
	}
	if snapshot.Workspace.Dashboard == nil || snapshot.Workspace.Dashboard.HTML == nil {
		return nil, nil, ErrNotFound
	}
	digest := snapshot.DashboardBundle
	if len(digest) != 64 || strings.Trim(digest, "0123456789abcdef") != "" {
		return nil, nil, ErrInvalid
	}
	var bundle DashboardBundle
	body, err := readFile(root, "state/dashboard-assets/"+digest+".json", 4<<20)
	if err != nil {
		return nil, nil, err
	}
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&bundle); err != nil {
		return nil, nil, err
	}
	if decoder.Decode(new(any)) != io.EOF {
		return nil, nil, ErrInvalid
	}
	actual, err := dashboardDigest(&bundle)
	if err != nil || actual != digest || bundle.Digest != digest {
		return nil, nil, ErrInvalid
	}
	html := snapshot.Workspace.Dashboard.HTML
	if bundle.Entry != html.Entry || !sameStrings(bundle.MetricIDs, html.MetricIDs) || !sameStrings(bundle.Libraries, html.Libraries) || len(bundle.Assets) != len(html.Assets) {
		return nil, nil, ErrInvalid
	}
	total := 0
	for _, name := range html.Assets {
		asset, ok := bundle.Assets[name]
		h := sha256.Sum256(asset.Body)
		total += len(asset.Body)
		if total > maxDashboardBundle || !utf8.Valid(asset.Body) || !ok || len(asset.Body) > maxDashboardFile || asset.MIMEType != dashboardAssetMIME(name) || hex.EncodeToString(h[:]) != asset.SHA256 {
			return nil, nil, ErrInvalid
		}
	}
	snapshot.Workspace.ProjectID = projectID
	return &bundle, &snapshot.Workspace, nil
}

func sameStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func dataURL(asset DashboardAsset) string {
	return "data:" + asset.MIMEType + ";charset=utf-8" + ";base64," + encodeDashboardAsset(asset.Body)
}
