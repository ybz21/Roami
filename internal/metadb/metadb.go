// Package metadb adapts core storage for the existing Web stores.
package metadb

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"sync"
	"time"

	"github.com/ybz21/Roami/backend/ttmux"
	core "github.com/ybz21/Roami/internal/storage"
	"github.com/ybz21/Roami/internal/tmuxruntime"

	_ "modernc.org/sqlite"
)

// Mode 是后端此刻的台账形态。
type Mode string

const (
	// ModeSQLite 直连 meta.db，读写正常。
	ModeSQLite Mode = "sqlite"
	// ModeLegacy 握手失败（没装 ttmux / 版本太老 / 库开不了）→ 退回旧的 JSON 台账。
	// 功能一个不掉，只是项目卡看不到会话历史。
	ModeLegacy Mode = "legacy-json"
)

// Info 是 `roami db status --json` 的输出。
type Info struct {
	Path      string         `json:"path"`
	Version   int            `json:"schemaVersion"`
	MinCompat int            `json:"minCompatible"`
	Journal   string         `json:"journalMode"`
	CLI       string         `json:"cliVersion"`
	Rows      map[string]int `json:"rows,omitempty"`
}

// backendKnows 是本二进制认得的 schema 版本。库比它新且 minCompatible 更高时退回 legacy。
const backendKnows = 3

// DB 是台账连接。Mode()==ModeLegacy 时 SQL() 为 nil，调用方走旧路径。
type DB struct {
	local *core.DB
	db    *sql.DB
	mode  Mode
	info  Info
	why   string
	wmu   sync.Mutex
}

func (d *DB) Mode() Mode   { return d.mode }
func (d *DB) Info() Info   { return d.info }
func (d *DB) Why() string  { return d.why }
func (d *DB) SQL() *sql.DB { return d.db }
func (d *DB) OK() bool     { return d != nil && d.mode == ModeSQLite && d.db != nil }
func (d *DB) Close() error {
	if d == nil || d.db == nil || d.local != nil {
		return nil
	}
	return d.db.Close()
}

// Open 握手并连上台账库。**永不返回 nil，也永不因为库的问题让后端起不来**：
// 终端、文件、浏览器这些和台账无关的功能不该被一个 SQLite 问题连坐
// （集群 hub 节点更是压根不跑业务，却照样会走到这里）。
func Open(ctx context.Context, tt *ttmux.Client, fallbackBin string) *DB {
	if tt.Local() {
		rt := runtime.New()
		d, err := core.Open(rt.HomeDir, core.Options{HomeDir: rt.HomeDir, DataDir: rt.DataDir})
		if err != nil {
			return legacy(err.Error())
		}
		v, _ := d.Version()
		return &DB{db: d.DB, local: d, mode: ModeSQLite, info: Info{Path: d.Path(), Version: v, MinCompat: 1, Journal: "wal"}}
	}

	info, err := handshake(ctx, tt, fallbackBin)
	if err != nil {
		return legacy(fmt.Sprintf("握手失败：%v", err))
	}
	if info.Path == "" {
		return legacy("ttmux 没报出库路径")
	}
	if info.MinCompat > backendKnows {
		return legacy(fmt.Sprintf("库要求读者 ≥ v%d，本后端只到 v%d", info.MinCompat, backendKnows))
	}
	if info.Version < backendKnows {
		return legacy(fmt.Sprintf("ttmux 的库还在 v%d（需要 v%d），先升级 ttmux", info.Version, backendKnows))
	}
	// 只带连接参数，不带任何 DDL：库已经由 CLI 建好、迁好。
	// _txlock=immediate 是必需的：Go 默认起 deferred 事务，「先读后写」会拿
	// SQLITE_BUSY_SNAPSHOT 立刻失败，不走 busy_timeout——而项目台账全是读改写。
	db, err := sql.Open("sqlite", "file:"+info.Path+
		"?_pragma=busy_timeout(10000)&_pragma=foreign_keys(1)&_txlock=immediate")
	if err != nil {
		return legacy(fmt.Sprintf("打开 %s 失败：%v", info.Path, err))
	}
	db.SetMaxOpenConns(4)
	db.SetMaxIdleConns(4)
	if err := db.PingContext(ctx); err != nil {
		db.Close()
		return legacy(fmt.Sprintf("连不上 %s：%v", info.Path, err))
	}
	for _, t := range []string{"projects", "project_aliases", "races", "session_homes", "sessions"} {
		var n int
		if err := db.QueryRow(`SELECT COUNT(*) FROM ` + t).Scan(&n); err != nil {
			db.Close()
			return legacy(fmt.Sprintf("库里缺表 %s：%v", t, err))
		}
	}
	log.Printf("台账：直连 %s（schema v%d，journal %s）", info.Path, info.Version, info.Journal)
	return &DB{db: db, mode: ModeSQLite, info: info}
}

func legacy(why string) *DB {
	log.Printf("台账：退回 JSON 文件 —— %s", why)
	return &DB{mode: ModeLegacy, why: why}
}

// handshake 问 ttmux 要库的位置与版本。
//
// **路径只能从这里拿**：CLI 的库在 ROAM_HOME 下，而后端的 dataDir 认的是 ROAM_DATA，
// 两者可以指到不同地方。后端自己 filepath.Join 的话，只设了 ROAM_DATA 的机器上会
// 静悄悄开出一个空库——项目和会话全不见，还查不出为什么。
func handshake(ctx context.Context, tt *ttmux.Client, fallbackBin string) (Info, error) {
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()

	info, err := askDB(ctx, tt)
	if err == nil {
		return info, nil
	}
	// PATH 上可能残留一个老 ttmux，而 roam 二进制是新的。内嵌那份能救回这种情况。
	// 注意：dev 构建里内嵌的是占位符，这条路走不通，只能靠 PATH。
	if fallbackBin != "" && fallbackBin != tt.Bin {
		if info, err2 := askDB(ctx, ttmux.New(fallbackBin)); err2 == nil {
			return info, nil
		}
	}
	return Info{}, err
}

func askDB(ctx context.Context, tt *ttmux.Client) (Info, error) {
	out, err := tt.RunCtx(ctx, "db", "status", "--json")
	if err != nil {
		return Info{}, fmt.Errorf("%s: %s", err, ttmux.StripANSI(out))
	}
	var info Info
	if err := json.Unmarshal([]byte(out), &info); err != nil {
		// 老 CLI 没有 db 子命令，会被 default 分支透传给 tmux，输出不是 JSON。
		return Info{}, fmt.Errorf("roami db status 不是 JSON（CLI 太老？）")
	}
	return info, nil
}

// Tx 在一个事务里跑 fn。写串行由 wmu 保证——两个进程写同一个库时，
// 少一个进程内的并发写者就少一分锁竞争。
func (d *DB) Tx(fn func(*sql.Tx) error) error {
	if d.local != nil {
		return d.local.Tx(fn)
	}
	if !d.OK() {
		return fmt.Errorf("metadb: 未直连（%s）", d.why)
	}
	d.wmu.Lock()
	defer d.wmu.Unlock()
	tx, err := d.db.Begin()
	if err != nil {
		return err
	}
	if err := fn(tx); err != nil {
		_ = tx.Rollback()
		return err
	}
	return tx.Commit()
}

// Exec 串行化的写。
func (d *DB) Exec(q string, args ...any) (sql.Result, error) {
	if d.local != nil {
		return d.local.Exec(q, args...)
	}
	if !d.OK() {
		return nil, fmt.Errorf("metadb: 未直连（%s）", d.why)
	}
	d.wmu.Lock()
	defer d.wmu.Unlock()
	return d.db.Exec(q, args...)
}

// Query / QueryRow 直接透传：WAL 下读不阻塞写，也不需要串行。
func (d *DB) Query(q string, args ...any) (*sql.Rows, error) {
	if !d.OK() {
		return nil, fmt.Errorf("metadb: 未直连（%s）", d.why)
	}
	return d.db.Query(q, args...)
}

func (d *DB) QueryRow(q string, args ...any) *sql.Row { return d.db.QueryRow(q, args...) }

// Reimport 报告是否要求重新收编旧 JSON（逃生口，正常不设）。
func Reimport() bool { return os.Getenv("ROAM_METADB_REIMPORT") == "1" }
