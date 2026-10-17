package metadb

import (
	"os"
	"path/filepath"
	"testing"
)

func touch(t *testing.T, path string) {
	t.Helper()
	if err := os.WriteFile(path, []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
}

func gone(t *testing.T, path string) bool {
	t.Helper()
	_, err := os.Stat(path)
	return os.IsNotExist(err)
}

// 留痕的退休不能挂在 v3 那个标记上。
//
// activity.log 是后来才收编的，而 v3 的标记在老机器上早就落下了——共用一个标记
// 等于「这台机器永远轮不到退休 activity.log」，源文件就一直躺在那儿，
// 下次谁再打开它就会看到一份与库分叉的旧数据。
func TestTracesRetireOnTheirOwnMark(t *testing.T) {
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, "migrations"), 0o755); err != nil {
		t.Fatal(err)
	}
	// 老机器的现场：v3 早已盖章，留痕文件还在
	touch(t, filepath.Join(dir, "migrations", legacyMark))
	touch(t, filepath.Join(dir, "activity.log"))
	touch(t, filepath.Join(dir, "activity.log.1"))

	RetireLegacyFiles(dir)

	for _, name := range traceFiles {
		if !gone(t, filepath.Join(dir, name)) {
			t.Fatalf("%s 应当已改名退休", name)
		}
	}
	if _, err := os.Stat(filepath.Join(dir, "migrations", traceMark)); err != nil {
		t.Fatal("应当落下留痕自己的标记")
	}
}

// 标记在 + 文件又出现（用户从备份恢复了）→ 不再改名，也不重导。
func TestRetireIsIdempotent(t *testing.T) {
	dir := t.TempDir()
	touch(t, filepath.Join(dir, "projects.json"))
	RetireLegacyFiles(dir)
	if !gone(t, filepath.Join(dir, "projects.json")) {
		t.Fatal("第一次应当改名")
	}
	touch(t, filepath.Join(dir, "projects.json")) // 从备份恢复回来
	RetireLegacyFiles(dir)
	if gone(t, filepath.Join(dir, "projects.json")) {
		t.Fatal("已收编过就不该再动它（重来会把已删的项目复活）")
	}
}
