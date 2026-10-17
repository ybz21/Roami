package reviewmesh

import (
	"strings"
	"testing"

	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

func TestResolveRounds(t *testing.T) {
	cases := []struct {
		name   string
		config string
		arg    string
		hasArg bool
		want   int
	}{
		{"default when unset", "", "", false, defaultAutoRounds},
		{"config overrides default", "5", "", false, 5},
		{"arg overrides config", "5", "8", true, 8},
		{"blank config falls back", "  ", "", false, defaultAutoRounds},
		{"non-numeric ignored", "abc", "", false, defaultAutoRounds},
		{"clamp below one", "0", "", false, 1},
		{"clamp above cap", "999", "", false, maxAutoRoundsCap},
		{"arg clamps too", "3", "-4", true, 1},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			ctx := &sdk.Ctx{Config: map[string]string{"rounds": tc.config}}
			var args map[string]string
			if tc.hasArg {
				args = map[string]string{"rounds": tc.arg}
			}
			if got := resolveRounds(ctx, args); got != tc.want {
				t.Fatalf("resolveRounds = %d, want %d", got, tc.want)
			}
		})
	}
}

func TestParseFindings(t *testing.T) {
	log := strings.Join([]string{
		"reviewer chattering...",
		"REVIEW_SUMMARY: 有两处需要修复的问题",
		"TTMUX_FINDINGS_BEGIN",
		"```json",
		`[{"severity":"high","title":"空指针","file":"a/b.go","line":10,"detail":"x 可能为 nil"},`,
		` {"title":"未处理错误","file":"a/c.go","line":22}]`,
		"```",
		"TTMUX_FINDINGS_END",
		"trailing noise",
	}, "\n")

	findings, summary, err := ParseFindings(log)
	if err != nil {
		t.Fatal(err)
	}
	if summary != "有两处需要修复的问题" {
		t.Fatalf("summary = %q", summary)
	}
	if len(findings) != 2 {
		t.Fatalf("want 2 findings, got %d", len(findings))
	}
	if findings[0].Severity != "high" || findings[0].Line != 10 {
		t.Fatalf("finding[0] wrong: %+v", findings[0])
	}
	if findings[1].Severity != "medium" { // 缺省补 medium
		t.Fatalf("default severity not applied: %+v", findings[1])
	}
}

func TestParseFindingsEmpty(t *testing.T) {
	log := "REVIEW_SUMMARY: 没有发现问题\nTTMUX_FINDINGS_BEGIN\n[]\nTTMUX_FINDINGS_END\n"
	findings, _, err := ParseFindings(log)
	if err != nil {
		t.Fatal(err)
	}
	if len(findings) != 0 {
		t.Fatalf("want 0 findings, got %d", len(findings))
	}
}

func TestParseFindingsMissingMarkers(t *testing.T) {
	if _, _, err := ParseFindings("no markers at all"); err == nil {
		t.Fatal("missing markers accepted")
	}
}

func TestParseSummaryUsesLastMatch(t *testing.T) {
	log := strings.Join([]string{
		"prompt echo: REVIEW_SUMMARY: <一句话结论>",
		"TTMUX_FINDINGS_BEGIN\n[]\nTTMUX_FINDINGS_END",
		"REVIEW_SUMMARY: 真正的总结在这里",
	}, "\n")
	_, summary, err := ParseFindings(log)
	if err != nil {
		t.Fatal(err)
	}
	if summary != "真正的总结在这里" {
		t.Fatalf("summary = %q", summary)
	}
}

func TestParseSummaryDropsPlaceholder(t *testing.T) {
	log := "REVIEW_SUMMARY: <一句话结论>\nTTMUX_FINDINGS_BEGIN\n[]\nTTMUX_FINDINGS_END"
	_, summary, err := ParseFindings(log)
	if err != nil {
		t.Fatal(err)
	}
	if summary != "" {
		t.Fatalf("placeholder not dropped: %q", summary)
	}
}

func TestParseFindingsUsesLastBlock(t *testing.T) {
	// prompt 本身包含标记说明文字时,必须取最后一个标记对(会话日志里
	// prompt 会被回显)。
	log := strings.Join([]string{
		"prompt echo: 请在 TTMUX_FINDINGS_BEGIN 与 TTMUX_FINDINGS_END 之间输出",
		"TTMUX_FINDINGS_BEGIN",
		`[{"severity":"low","title":"first block"}]`,
		"TTMUX_FINDINGS_END",
		"TTMUX_FINDINGS_BEGIN",
		`[{"severity":"high","title":"real block"}]`,
		"TTMUX_FINDINGS_END",
	}, "\n")
	findings, _, err := ParseFindings(log)
	if err != nil {
		t.Fatal(err)
	}
	if len(findings) != 1 || findings[0].Title != "real block" {
		t.Fatalf("did not use last block: %+v", findings)
	}
}
