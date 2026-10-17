// Package webui 内嵌前端构建产物（frontend/dist），让 roam 成为单一自包含二进制。
//
// 构建时由 CI/脚本把 frontend/dist 拷进本目录的 site/（gitignored；仓库只保留 .gitkeep 占位）。
// 运行时把内嵌产物解压到 <home>/webui/<hash>/ 一次，复用后端既有的磁盘挂载逻辑
// （含 .br/.gz 预压缩产物直发），无需为内嵌单独实现一套静态服务。
package webui

import (
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"io/fs"
	"os"
	"path/filepath"
)

//go:embed all:site
var distFS embed.FS

// sub 返回 site/ 子树（内嵌的 frontend/dist 内容）；仅在确有真实构建（存在 index.html）时返回 ok=true。
func sub() (fs.FS, bool) {
	s, err := fs.Sub(distFS, "site")
	if err != nil {
		return nil, false
	}
	if _, err := fs.Stat(s, "index.html"); err != nil {
		return nil, false // 只有 .gitkeep 占位，无真实构建
	}
	return s, true
}

// Embedded 报告是否内嵌了真实前端构建。
func Embedded() bool {
	_, ok := sub()
	return ok
}

// Ensure 把内嵌前端解压到 baseDir/webui/<hash>/（幂等，靠 index.html 内容 hash 命名，
// 内容不变则跳过），返回含 index.html 的目录。无真实构建时返回 ""。
func Ensure(baseDir string) string {
	s, ok := sub()
	if !ok {
		return ""
	}
	index, err := fs.ReadFile(s, "index.html")
	if err != nil {
		return ""
	}
	sum := sha256.Sum256(index)
	dir := filepath.Join(baseDir, "webui", hex.EncodeToString(sum[:])[:12])
	stamp := filepath.Join(dir, ".ok")
	if _, err := os.Stat(stamp); err == nil {
		return dir
	}
	if err := extract(s, dir); err != nil {
		return ""
	}
	_ = os.WriteFile(stamp, []byte("ok"), 0o644)
	return dir
}

func extract(s fs.FS, dir string) error {
	return fs.WalkDir(s, ".", func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		target := filepath.Join(dir, p)
		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		data, err := fs.ReadFile(s, p)
		if err != nil {
			return err
		}
		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}
		return os.WriteFile(target, data, 0o644)
	})
}
