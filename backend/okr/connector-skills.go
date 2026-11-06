package okr

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"path"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

type ConnectorMetric struct {
	MetricID string `json:"metricId"`
	Field    string `json:"field"`
}

type SkillConnector struct {
	Window        string            `json:"window"`
	ID            string            `json:"id"`
	Name          string            `json:"name"`
	Service       string            `json:"service"`
	Identity      string            `json:"identity"`
	Repo          string            `json:"repo,omitempty"`
	Timezone      string            `json:"timezone"`
	Files         []string          `json:"files"`
	Bindings      []ConnectorMetric `json:"bindings"`
	PackageSHA256 string            `json:"packageSha256,omitempty"`
}

type skillConnectorDefinition struct {
	SchemaVersion int            `json:"schemaVersion"`
	Execution     string         `json:"execution"`
	Skill         SkillConnector `json:"skill"`
}

func validDigest(value string) bool {
	b, err := hex.DecodeString(value)
	return err == nil && len(b) == sha256.Size && value == strings.ToLower(value)
}

func connectorMetric(c *Config, metricID string) (*SkillConnector, string) {
	for i := range c.Connectors {
		for _, binding := range c.Connectors[i].Bindings {
			if binding.MetricID == metricID {
				return &c.Connectors[i], binding.Field
			}
		}
	}
	return nil, ""
}

func validateConnectorSkills(c *Config) error {
	if len(c.Connectors) > 32 {
		return ErrInvalid
	}
	metrics := map[string]Metric{}
	for _, metric := range c.Metrics {
		metrics[metric.ID] = metric
	}
	ids, bound := map[string]bool{}, map[string]bool{}
	for _, connector := range c.Connectors {
		if !identifier.MatchString(connector.ID) || ids[strings.ToLower(connector.ID)] || metrics[connector.ID].ID != "" || strings.TrimSpace(connector.Name) == "" || utf8.RuneCountInString(connector.Name) > 80 || !identifier.MatchString(connector.Service) || strings.TrimSpace(connector.Identity) != connector.Identity || connector.Identity == "" || len(connector.Identity) > 512 || len(connector.Files) == 0 || len(connector.Files) > 32 || len(connector.Bindings) == 0 || len(connector.Bindings) > 64 || connector.PackageSHA256 != "" && !validDigest(connector.PackageSHA256) {
			return ErrInvalid
		}
		if _, err := time.LoadLocation(connector.Timezone); err != nil || connector.Timezone == "" || connector.Timezone == "Local" {
			return ErrInvalid
		}
		for metricID := range metrics {
			if strings.EqualFold(metricID, connector.ID) {
				return ErrInvalid
			}
		}
		if connector.Window != "snapshot" && connector.Window != "day" {
			return ErrInvalid
		}
		if connector.Service == "github" {
			for metricID := range metrics {
				if strings.EqualFold(metricID, connector.ID) {
					return ErrInvalid
				}
			}
			if connector.Window != "snapshot" || connector.Timezone != "Asia/Shanghai" {
				return ErrInvalid
			}
			repositoryID, err := strconv.ParseInt(connector.Identity, 10, 64)
			if err != nil || repositoryID <= 0 || strconv.FormatInt(repositoryID, 10) != connector.Identity || !repository.MatchString(connector.Repo) {
				return ErrInvalid
			}
		} else if connector.Repo != "" {
			return ErrInvalid
		}
		files := map[string]bool{}
		for _, name := range connector.Files {
			if !fs.ValidPath(name) || files[name] || strings.ContainsAny(name, `\:%?#`) || name == "connector.json" || strings.HasPrefix(name, ".") {
				return ErrInvalid
			}
			files[name] = true
		}
		if !files["SKILL.md"] {
			return ErrInvalid
		}
		fields := map[string]bool{}
		for _, binding := range connector.Bindings {
			metric, ok := metrics[binding.MetricID]
			if !ok || bound[metric.ID] || !identifier.MatchString(binding.Field) || fields[binding.Field] {
				return ErrInvalid
			}
			if connector.Service == "github" {
				if metric.Source != "github" || !strings.EqualFold(metric.Repo, connector.Repo) || metric.Field != binding.Field {
					return ErrInvalid
				}
			} else if metric.Source != "manual" {
				return ErrInvalid
			}
			bound[metric.ID], fields[binding.Field] = true, true
		}
		ids[strings.ToLower(connector.ID)] = true
	}
	return nil
}

func connectorSourceKey(connector SkillConnector, field string, metric Metric) string {
	if connector.Service == "github" {
		return "github:" + connector.Identity + ":" + field
	}
	b, _ := json.Marshal([]string{connector.Service, connector.Identity, field, metric.Unit, connector.Timezone, connector.Window})
	return "skill:" + hashText(b)
}

// Hash declared files only; a Skill package is guidance, never a host command entrypoint.
func connectorPackage(root *os.Root, connector SkillConnector) (string, error) {
	digests, total := map[string]string{}, 0
	for _, name := range connector.Files {
		body, err := readFile(root, path.Join("connectors", connector.ID, name), 1<<20)
		if err != nil {
			return "", err
		}
		total += len(body)
		if total > 2<<20 || name == "SKILL.md" && (len(body) > maxMemory || !utf8.Valid(body) || !bytes.HasPrefix(body, []byte("---\n"))) {
			return "", ErrInvalid
		}
		digests[name] = hashText(body)
	}
	body, err := json.Marshal(digests)
	if err != nil {
		return "", err
	}
	return hashText(body), nil
}

func confirmConnectorPackages(root *os.Root, c *Config, checkExpected bool) error {
	for i := range c.Connectors {
		connector := &c.Connectors[i]
		digest, err := connectorPackage(root, *connector)
		if err != nil {
			return err
		}
		if checkExpected && connector.PackageSHA256 != "" && connector.PackageSHA256 != digest {
			return ErrConflict
		}
		connector.PackageSHA256 = digest
	}
	return nil
}

func workingConnectorSkills(root *os.Root, c *Config) error {
	for _, connector := range c.Connectors {
		var definition skillConnectorDefinition
		if err := decodeFile(root, path.Join("connectors", connector.ID, "connector.json"), &definition); err != nil {
			return err
		}
		expected, _ := json.Marshal(skillConnectorDefinition{2, "skill", connector})
		actual, _ := json.Marshal(definition)
		if !bytes.Equal(expected, actual) {
			return fmt.Errorf("%w: connector %s", ErrInvalid, connector.ID)
		}
	}
	return confirmConnectorPackages(root, c, false)
}

const connectorBatchProtocol = `Connector Skill batches v1. This is the current host's protocol; use project_okr_update operation=save/record, not shell or database writes.
Config.connectors is an optional list. Omission preserves existing bindings; [] explicitly removes them. Each entry: {id,name,service,identity,repo?,timezone,window,files,bindings,packageSha256?}. IDs differ from metric IDs. Files are relative to connectors/<id>/, must include SKILL.md, and declare all reviewed workflow code. Bindings are [{metricId,field}], each metric bound once. Source identity, timezone, window and units define the measurement. window=snapshot uses equal window endpoints; window=day uses a local-midnight start and exclusive end no later than the next local midnight. Supported timezones are IANA names.
For service=github, identity is the positive numeric repository ID as a string, repo matches all bound github metrics and fields (stars/forks), timezone=Asia/Shanghai, window=snapshot. This preserves existing GitHub history. Other services bind explicit/manual metrics to source/account identity, separating their source keys from old unbound observations. The host validates declared files and confirms packageSha256; changed code remains pending until reviewed save/sync. Editing metadata does not execute code. Existing builtin GitHub autoCollect remains a separate compatibility collector, not a Skill schedule.
Have the original managed member run the reviewed Skill with its authorized Python/MCP tools. Main must read the current-run evidence and check external source/account, measurement semantics and actual task result. Then operation=record, payload={revision,batch:{id,connectorId,packageSha256,sourceIdentity,date,capturedAt,windowStart,windowEnd,values,evidence,note?}}. id is a caller-generated 32-lowercase-hex batch key, not a fabricated task/run ID. values=[{metricId,unit,value}] requires explicit finite numbers and exact confirmed units; absent observations are omitted, never invented zero. evidence=[{path,sha256}] uses project-relative real files, raw-byte SHA256. capturedAt/windowStart/windowEnd use RFC3339. GitHub requires a raw public repository JSON response whose ID, name and counts match the batch, and snapshot endpoints equal capturedAt. External responses require Main's semantic review; hashes do not prove remote truth or execution.
The host reads bounded regular files without symlinks, archives exact evidence bytes and commits observations plus connectorBatches receipt under one confirmed revision pointer. A batch receipt means data publication only, not task verification, account authorization or a daily schedule. Reconcile an unknown result by reading connectorBatches for the same id; retry the exact original revision/payload/key. Reused keys with changed content conflict; writes never silently retry against another revision. Keep source failures as unknown and retain prior facts. Daily Skill execution needs a real scheduler/nextDue receipt and the user's time/timezone decision.`
