package swarm

import (
	"path/filepath"
	"testing"
	"time"

	_ "modernc.org/sqlite"
)

func TestSubroleNorm(t *testing.T) {
	cases := map[string]string{
		"前端": "frontend", "engineer": "engineer", "QA": "qa", "测试工程师": "qa",
		"architect": "architect", "": "", "  custom-x ": "custom-x",
	}
	for in, want := range cases {
		if got := SubroleNorm(in); got != want {
			t.Errorf("SubroleNorm(%q)=%q want %q", in, got, want)
		}
	}
}

func TestSubroleDutyRoundTrip(t *testing.T) {
	home := filepath.Join(t.TempDir(), "h")
	opt := Options{HomeDir: home, DataDir: filepath.Join(home, "data"), Now: func() time.Time { return time.Unix(100, 0) }}
	st := NewStore(opt)
	if _, err := st.NewSwarm("sw", "goal", ""); err != nil {
		t.Fatal(err)
	}
	// 细分角色用别名写入，应被 SubroleNorm 归一为 frontend
	if err := st.AddMemberRow("sw", MemberSpec{Name: "ui", Type: "agent", Task: "t", Kind: "claude", Role: "member", Subrole: "前端", Duty: "负责看板前端"}); err != nil {
		t.Fatal(err)
	}
	stt, err := Status("sw", opt)
	if err != nil {
		t.Fatal(err)
	}
	var m *SwarmMember
	for i := range stt.Members {
		if stt.Members[i].Name == "ui" {
			m = &stt.Members[i]
		}
	}
	if m == nil {
		t.Fatalf("member ui missing: %+v", stt.Members)
	}
	if m.Subrole != "frontend" {
		t.Errorf("subrole=%q want frontend", m.Subrole)
	}
	if m.Duty != "负责看板前端" {
		t.Errorf("duty=%q want 负责看板前端", m.Duty)
	}
}
