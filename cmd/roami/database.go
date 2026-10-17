package main

import (
	"database/sql"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"github.com/ybz21/Roami/backend/config"
	metadb "github.com/ybz21/Roami/internal/storage"
)

func runDatabase(args []string) int {
	sub := "status"
	if len(args) > 0 {
		sub = args[0]
		args = args[1:]
	}
	if sub == "help" || sub == "--help" || sub == "-h" {
		fmt.Println("roami db status|migrate|backup|restore [--json]\n  migrate --layout --dry-run | --layout --offline | --recover\n  restore <backup-set>: restore into an empty instance")
		return 0
	}
	fs := flag.NewFlagSet("db "+sub, flag.ContinueOnError)
	asJSON := fs.Bool("json", false, "JSON")
	layout := fs.Bool("layout", false, "迁移旧数据库目录")
	dry := fs.Bool("dry-run", false, "只读盘点")
	offline := fs.Bool("offline", false, "已停止全部旧版本写者")
	recover := fs.Bool("recover", false, "恢复中断的布局发布")
	var positional []string
	var flags []string
	for _, a := range args {
		if len(a) > 0 && a[0] == '-' {
			flags = append(flags, a)
		} else {
			positional = append(positional, a)
		}
	}
	if e := fs.Parse(flags); e != nil {
		return 2
	}
	p, e := metadb.ResolvePaths(config.Home(), dataDir())
	if e != nil {
		fmt.Fprintln(os.Stderr, e)
		return 1
	}
	var result any
	switch sub {
	case "help", "--help", "-h":
		fmt.Println("roami db status|migrate|backup|restore [--json]\n  migrate --layout --dry-run | --layout --offline | --recover\n  restore <backup-set>: restore into an empty instance")
		return 0
	case "status":
		l, err := p.ReadLayout()
		if err != nil {
			if !os.IsNotExist(err) {
				e = err
				break
			}
			plan, pe := metadb.PlanLayout(p)
			if pe != nil {
				e = pe
				break
			}
			result = map[string]any{"path": p.MainPath(), "layoutVersion": 0, "mode": "uninitialized", "migrationRequired": len(plan.Databases) > 0, "paths": p, "plan": plan}
			break
		}
		c, err := p.Catalog()
		if err != nil {
			e = err
			break
		}
		db, err := sql.Open("sqlite", "file:"+p.MainPath()+"?mode=ro")
		if err != nil {
			e = err
			break
		}
		defer db.Close()
		var schema int
		var journal string
		if err = db.QueryRow("SELECT COALESCE(MAX(version),0) FROM schema_meta").Scan(&schema); err != nil {
			e = err
			break
		}
		_ = db.QueryRow("PRAGMA journal_mode").Scan(&journal)
		result = map[string]any{"path": p.MainPath(), "schemaVersion": schema, "minCompatible": 1, "cliVersion": displayVersion(), "journalMode": journal, "layoutVersion": l.Version, "instanceId": l.Instance, "paths": p, "databases": c.Databases, "mode": "sqlite"}
	case "migrate":
		if *recover {
			e = p.RecoverLayout()
		} else if *layout {
			if *dry {
				result, e = metadb.PlanLayout(p)
			} else {
				e = p.MigrateLayout(*offline)
			}
		} else {
			var d *metadb.DB
			d, e = metadb.Open(p.Home, metadb.Options{HomeDir: p.Home, DataDir: p.Data})
			if e == nil {
				v, _ := d.Version()
				result = map[string]any{"path": d.Path(), "schemaVersion": v}
			}
		}
	case "backup":
		dest := ""
		if len(positional) > 0 {
			dest = positional[0]
		}
		result, e = p.BackupSet(dest)
	case "restore":
		if len(positional) != 1 {
			e = fmt.Errorf("需要一个备份集路径")
		} else {
			source, _ := filepath.Abs(positional[0])
			e = p.RestoreSet(source)
		}
	default:
		return runSessionEngine(append([]string{"db", sub}, args...))
	}
	if e != nil {
		if *asJSON {
			b, _ := json.Marshal(map[string]any{"error": map[string]string{"code": "STORAGE_ERROR", "message": e.Error()}})
			fmt.Println(string(b))
		} else {
			fmt.Fprintln(os.Stderr, e)
		}
		return 1
	}
	if result == nil {
		result = map[string]bool{"ok": true}
	}
	b, e := json.MarshalIndent(result, "", "  ")
	if e != nil {
		fmt.Fprintln(os.Stderr, e)
		return 1
	}
	_ = asJSON
	fmt.Println(string(b))
	return 0
}
