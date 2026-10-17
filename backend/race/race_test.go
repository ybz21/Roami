package race

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"testing"

	"github.com/ybz21/Roami/internal/id"
)

// 老竞赛记录（race-<纳秒>）加载时统一重写成可读 id；老 id 落 legacyId，
// 已经打开的页面按老 id 还能找到本场竞赛。
func TestRaceStoreNormalizesLegacyIDs(t *testing.T) {
	dir := t.TempDir()
	legacy := `[{"id":"race-1753670000000000000","name":"demo","dir":"/repo","status":"running","contestants":[]}]`
	if err := os.WriteFile(filepath.Join(dir, "races.json"), []byte(legacy), 0o600); err != nil {
		t.Fatal(err)
	}
	s := NewStore(dir, nil)
	if len(s.races) != 1 {
		t.Fatalf("races = %+v", s.races)
	}
	r := s.races[0]
	if !id.Valid(r.ID) {
		t.Fatalf("id 应重写成可读格式，got %q", r.ID)
	}
	if r.LegacyID != "race-1753670000000000000" {
		t.Fatalf("legacyId = %q", r.LegacyID)
	}
	if s.get("race-1753670000000000000") == nil || s.get(r.ID) == nil {
		t.Fatal("新老 id 都应能查到")
	}
	// 重写落盘：重开不再二次改写
	s2 := NewStore(dir, nil)
	if s2.races[0].ID != r.ID {
		t.Fatalf("重写未落盘或被二次改写: %q vs %q", s2.races[0].ID, r.ID)
	}
	var raw []map[string]any
	b, _ := os.ReadFile(filepath.Join(dir, "races.json"))
	if json.Unmarshal(b, &raw) != nil || raw[0]["legacyId"] != "race-1753670000000000000" {
		t.Fatalf("落盘内容缺 legacyId: %s", b)
	}
}

// List/Get 返回的必须是深拷贝：调用方改了手上那份，台账不能跟着变。
// 以前 handler 直接拿到 *Race 指针，改一改就悄悄改了台账。
func TestReadsAreDeepCopies(t *testing.T) {
	s := NewStore(t.TempDir(), nil)
	s.Create(&Race{ID: "r1", Name: "n", Status: "running", Dir: "/repo",
		CrownDone:   []string{"merge"},
		Contestants: []Contestant{{Session: "a", Status: "running"}}})

	got, ok := s.Get("r1")
	if !ok {
		t.Fatal("取不到")
	}
	got.Name = "改了"
	got.CrownDone[0] = "篡改"
	got.Contestants[0].Session = "篡改"

	again, _ := s.Get("r1")
	if again.Name != "n" || again.CrownDone[0] != "merge" || again.Contestants[0].Session != "a" {
		t.Fatalf("台账被外部改动污染了: %+v", again)
	}
}

// Update 的 fn 报错 = 一个字节都不写。
func TestUpdateRollsBackOnError(t *testing.T) {
	s := NewStore(t.TempDir(), nil)
	s.Create(&Race{ID: "r1", Status: "running"})
	boom := errors.New("boom")
	if _, err := s.Update("r1", func(r *Race) error { r.Status = "crowned"; return boom }); err != boom {
		t.Fatalf("应当原样返回 fn 的错误, got %v", err)
	}
	got, _ := s.Get("r1")
	if got.Status != "running" {
		t.Fatalf("fn 出错却写进去了: %q", got.Status)
	}
}

// MarkStage 幂等（失败续跑要靠它），FreezeWinner 换人清空阶段。
func TestCrownStateMachine(t *testing.T) {
	s := NewStore(t.TempDir(), nil)
	s.Create(&Race{ID: "r1", Status: "running"})

	if _, err := s.FreezeWinner("r1", "alice"); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 3; i++ {
		if _, err := s.MarkStage("r1", "merge"); err != nil {
			t.Fatal(err)
		}
	}
	got, _ := s.Get("r1")
	if len(got.CrownDone) != 1 || got.CrownDone[0] != "merge" {
		t.Fatalf("MarkStage 不幂等: %v", got.CrownDone)
	}
	if !StageDone(got, "merge") || StageDone(got, "cleanup") {
		t.Fatal("StageDone 判错")
	}
	// 换赢家：上一轮走过的阶段必须清掉，否则新一轮会跳过该做的合并
	next, err := s.FreezeWinner("r1", "bob")
	if err != nil {
		t.Fatal(err)
	}
	if len(next.CrownDone) != 0 || next.Winner != "bob" {
		t.Fatalf("换赢家没清空阶段: %+v", next)
	}
}

// 并发 crown：以前是「拿到指针 → 解锁 → 在 git 操作之间无锁读写 CrownDone」，
// 两个请求撞上就是数据竞争。现在全走 Update，-race 下也必须干净。
func TestConcurrentMarkStageIsSafe(t *testing.T) {
	s := NewStore(t.TempDir(), nil)
	s.Create(&Race{ID: "r1", Status: "running"})
	stages := []string{"wip-commit", "merge", "cleanup"}
	var wg sync.WaitGroup
	for i := 0; i < 12; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			if _, err := s.MarkStage("r1", stages[i%len(stages)]); err != nil {
				t.Errorf("MarkStage: %v", err)
			}
		}(i)
	}
	wg.Wait()
	got, _ := s.Get("r1")
	if len(got.CrownDone) != len(stages) {
		t.Fatalf("并发下阶段数不对: %v", got.CrownDone)
	}
}

// RunningByDir 收口了项目页那处跨文件裸访问：只数 running，目录归一化。
func TestRunningByDir(t *testing.T) {
	s := NewStore(t.TempDir(), nil)
	s.Create(&Race{ID: "a", Status: "running", Dir: "/repo/x"})
	s.Create(&Race{ID: "b", Status: "running", Dir: "/repo/x/"})
	s.Create(&Race{ID: "c", Status: "cleaned", Dir: "/repo/x"})
	s.Create(&Race{ID: "d", Status: "running", Dir: ""})
	got := s.RunningByDir()
	if got["/repo/x"] != 2 || len(got) != 1 {
		t.Fatalf("RunningByDir = %v, want {/repo/x:2}", got)
	}
}
