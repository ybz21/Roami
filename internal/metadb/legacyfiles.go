package metadb

import (
	"fmt"
	"log"
	"os"
	"path/filepath"
	"time"
)

// 旧 JSON 台账的收尾。
//
// 收编本身由 CLI 做（它在 metadb 的版本链里把 projects.json / races.json /
// session-homes.json 读进库）。**改名只能由后端做**：后端是这三个文件此刻的活写者，
// CLI 单方面改完名，后端下一次 save() 就会原地复活一个新 JSON，真相当场分叉。
// 所以顺序是：后端确认自己已经直连、已经从库里读到数据 → 才把源文件改名。

const legacyMark = "metadb-v3.done"

// traceMark 单独一个标记：留痕（activity.log）是后来才收编的，那时 v3 的标记
// 在老机器上早就落下了。共用一个标记等于「这台机器永远轮不到退休 activity.log」。
const traceMark = "metadb-traces.done"

var legacyFiles = []string{"projects.json", "races.json", "session-homes.json"}

// traceFiles 是两代留痕（当代 + 轮转出去的那一代）。
var traceFiles = []string{"activity.log", "activity.log.1"}

// RetireLegacyFiles 把已收编的旧台账改名 <文件>.bak-<时间>，并落一个幂等标记。
func RetireLegacyFiles(dataDir string) {
	retire(dataDir, legacyMark, legacyFiles)
	retire(dataDir, traceMark, traceFiles)
}

// retire 退休一组已收编的源文件。
//
// **标记在 + 文件又出现 → 不重导也不再改名**，只告警：用户可能是从备份恢复了旧文件，
// 重来一遍会把已经删掉的项目、已经清理的竞赛统统复活。想强来设 ROAM_METADB_REIMPORT=1。
func retire(dataDir, markName string, files []string) {
	if dataDir == "" {
		return
	}
	mark := filepath.Join(dataDir, "migrations", markName)
	_, marked := os.Stat(mark)
	present := existing(dataDir, files)

	if marked == nil { // 标记已在
		if len(present) > 0 && !Reimport() {
			log.Printf("台账：旧 JSON 又出现了（%v），已收编过所以不再重来；"+
				"确实要重导请设 ROAM_METADB_REIMPORT=1", present)
		}
		return
	}
	stamp := time.Now().Format("20060102-150405")
	for _, name := range present {
		src := filepath.Join(dataDir, name)
		dst := src + ".bak-" + stamp
		if err := os.Rename(src, dst); err != nil {
			log.Printf("台账：%s 改名失败（下次再来）: %v", name, err)
			return // 一个都没退休成功就别落标记
		}
		log.Printf("台账：%s → %s", name, filepath.Base(dst))
	}
	if err := os.MkdirAll(filepath.Dir(mark), 0o755); err != nil {
		return
	}
	_ = os.WriteFile(mark, []byte(fmt.Sprintf("%s %s\n", markName, stamp)), 0o644)
}

func existing(dataDir string, files []string) []string {
	var out []string
	for _, name := range files {
		if _, err := os.Stat(filepath.Join(dataDir, name)); err == nil {
			out = append(out, name)
		}
	}
	return out
}
