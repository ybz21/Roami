// 文件服务：供对话页（Claude / Codex）右侧文件侧栏浏览工作目录、查看文件内容。
// 整个 Web 控制台已是口令鉴权且提供终端全访问，这里读文件与之一致，不再额外限制根目录。
package api

import (
	"archive/zip"
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

type fileEntry struct {
	Name  string `json:"name"`
	Dir   bool   `json:"dir"`
	Size  int64  `json:"size"`
	Mtime int64  `json:"mtime"`
	Ctime int64  `json:"ctime"`
}

type fileStatData struct {
	Path       string `json:"path"`
	Name       string `json:"name"`
	Dir        bool   `json:"dir"`
	Size       int64  `json:"size"`
	Mtime      int64  `json:"mtime"`
	Ctime      int64  `json:"ctime"`
	Mode       string `json:"mode"`
	EntryCount int    `json:"entryCount,omitempty"`
}

// Files GET /files?path=<dir> —— 列出目录内容（目录在前，按名排序）。
// macOS TCC 保护目录（~/Downloads 等）在无权限时 ReadDir 会无限阻塞，因此加超时兜底。
func (a *API) Files(c *gin.Context) {
	p := c.Query("path")
	if p == "" {
		home, _ := os.UserHomeDir()
		p = home
	}
	p = filepath.Clean(p)

	type readResult struct {
		entries []os.DirEntry
		err     error
	}
	ch := make(chan readResult, 1)
	go func() {
		entries, err := os.ReadDir(p)
		ch <- readResult{entries, err}
	}()
	select {
	case res := <-ch:
		if res.err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "FS_ERROR", "message": res.err.Error()}})
			return
		}
		list := []fileEntry{}
		for _, e := range res.entries {
			var size, mtime, ctime int64
			if info, err := e.Info(); err == nil {
				size = info.Size()
				mtime = info.ModTime().Unix()
				ctime = fileCtime(info)
			}
			list = append(list, fileEntry{Name: e.Name(), Dir: e.IsDir(), Size: size, Mtime: mtime, Ctime: ctime})
		}
		sort.Slice(list, func(i, j int) bool {
			if list[i].Dir != list[j].Dir {
				return list[i].Dir
			}
			return list[i].Name < list[j].Name
		})
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"path": p, "parent": filepath.Dir(p), "entries": list}})
	case <-time.After(3 * time.Second):
		c.JSON(http.StatusGatewayTimeout, gin.H{"error": gin.H{
			"code": "DIR_ACCESS_TIMEOUT",
			"path": p,
		}})
	}
}

const fileReadCap = 512 * 1024 // 单文件正文上限，超出截断

// File GET /file?path=<file> —— 读取文件内容（限大小；含 NUL 的二进制不返回正文）。
func (a *API) File(c *gin.Context) {
	p := filepath.Clean(c.Query("path"))
	if p == "" || !filepath.IsAbs(p) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	info, err := os.Stat(p)
	if err != nil || info.IsDir() {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "NOT_FILE"}})
		return
	}
	f, err := os.Open(p)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "READ_ERROR", "message": err.Error()}})
		return
	}
	defer f.Close()

	data, _ := io.ReadAll(io.LimitReader(f, fileReadCap+1))
	truncated := false
	if len(data) > fileReadCap {
		data = data[:fileReadCap]
		truncated = true
	}
	binary := bytes.IndexByte(data, 0) >= 0
	content := ""
	if !binary {
		content = string(data)
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{
		"path": p, "size": info.Size(), "mtime": info.ModTime().Unix(), "truncated": truncated, "binary": binary, "content": content,
	}})
}

// FileSave POST /file/save —— 覆盖写入已存在的普通文件内容（编辑器保存用）。
// 只允许覆盖既有普通文件（新建走 upload/mkdir），并保留原文件权限位。
func (a *API) FileSave(c *gin.Context) {
	var req struct {
		Path    string `json:"path"`
		Content string `json:"content"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_FORM", "message": err.Error()}})
		return
	}
	p := filepath.Clean(req.Path)
	if p == "" || !filepath.IsAbs(p) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	info, err := os.Stat(p)
	if err != nil || info.IsDir() {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "NOT_FILE"}})
		return
	}
	if err := os.WriteFile(p, []byte(req.Content), info.Mode().Perm()); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "WRITE_ERROR", "message": err.Error()}})
		return
	}
	var size, mtime int64
	if ni, err := os.Stat(p); err == nil {
		size = ni.Size()
		mtime = ni.ModTime().Unix()
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"path": p, "size": size, "mtime": mtime}})
}

// FileSearch GET /file/search?dir=<dir>&q=<query> —— 从 dir 递归按文件名模糊(子串,忽略大小写)搜文件。
// 有界：跳过 .git/node_modules，限制访问条目与返回条数，避免大目录卡死。
func (a *API) FileSearch(c *gin.Context) {
	dir := filepath.Clean(c.Query("dir"))
	q := strings.TrimSpace(c.Query("q"))
	if dir == "" || !filepath.IsAbs(dir) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	type hit struct {
		Path string `json:"path"`
		Name string `json:"name"`
		Rel  string `json:"rel"`
	}
	results := []hit{}
	if q == "" {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"results": results, "truncated": false}})
		return
	}
	// 匹配器：优先当正则(忽略大小写、不锚定)；正则非法(如 *.py 以 * 开头)则按 glob 再试；
	// 都不行退化为子串包含。这样纯文字=子串，a*.py / *.py 等通配也能用。
	ql := strings.ToLower(q)
	re, err := regexp.Compile("(?i)" + q)
	if err != nil {
		re, err = regexp.Compile("(?i)^" + globToRegex(q) + "$")
		if err != nil {
			re = nil
		}
	}
	match := func(name string) bool {
		if re != nil {
			return re.MatchString(name)
		}
		return strings.Contains(strings.ToLower(name), ql)
	}
	const maxResults, maxVisited = 200, 50000
	visited := 0
	truncated := false
	skipDir := map[string]bool{".git": true, "node_modules": true}
	_ = filepath.WalkDir(dir, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return nil // 跳过不可读条目
		}
		if len(results) >= maxResults || visited >= maxVisited {
			truncated = true
			return filepath.SkipAll
		}
		if d.IsDir() {
			if p != dir && skipDir[d.Name()] {
				return filepath.SkipDir
			}
			return nil
		}
		visited++
		if match(d.Name()) {
			rel, _ := filepath.Rel(dir, p)
			results = append(results, hit{Path: p, Name: d.Name(), Rel: rel})
		}
		return nil
	})
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"results": results, "truncated": truncated}})
}

// globToRegex 把 shell 通配(*,?)转成正则片段，其余字符原样转义。用于 *.py 这类 glob 搜索。
func globToRegex(g string) string {
	var b strings.Builder
	for _, r := range g {
		switch r {
		case '*':
			b.WriteString(".*")
		case '?':
			b.WriteString(".")
		default:
			b.WriteString(regexp.QuoteMeta(string(r)))
		}
	}
	return b.String()
}

// FileRaw GET /file/raw?path=<file> —— 原样返回文件字节（图片等内联预览用，Content-Type 按扩展名嗅探）。
func (a *API) FileRaw(c *gin.Context) {
	p := filepath.Clean(c.Query("path"))
	if p == "" || !filepath.IsAbs(p) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	info, err := os.Stat(p)
	if err != nil || info.IsDir() {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "NOT_FILE"}})
		return
	}
	if c.Query("dl") != "" { // 强制下载（附件），带原文件名
		serveAttachment(c, p, filepath.Base(p))
		return
	}
	c.File(p)
}

// FilePath accepts legacy links with the file path appended directly to /api/file.
func (a *API) FilePath(c *gin.Context) {
	p := strings.TrimPrefix(c.Request.URL.Path, "/api/file/")
	p = strings.TrimPrefix(p, "raw/")
	if p == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	// A single separator commonly stands for the filesystem root; relative links fall back to cwd.
	absolute := filepath.Clean("/" + p)
	if _, err := os.Stat(absolute); !os.IsNotExist(err) {
		p = absolute
	} else {
		var err error
		p, err = filepath.Abs(p)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
			return
		}
	}
	c.Params = append(c.Params, gin.Param{Key: "path", Value: p})
	a.FileServe(c)
}

// FileServe GET /file/serve/*path —— 把文件绝对路径直接编进 URL 路径来提供文件
// （区别于 /file/raw 的 ?path= 查询参数）。这样 HTML 内的同目录相对引用（style.css、
// ./app.js、../img/x.png）会被浏览器按 URL 相对规则解析到同目录资源，再命中本路由取到
// 文件，相当于一个以文件系统为根的静态文件服务。暴露面与 /file/raw 一致（都能读任意
// 可访问的绝对路径文件，已在鉴权后）。仅供 HTML 预览 iframe 使用。
func (a *API) FileServe(c *gin.Context) {
	p := filepath.Clean(c.Param("path")) // *path 含前导斜杠 → 即绝对路径；Clean 顺带归一化 .. 段
	if p == "" || p == "/" || !filepath.IsAbs(p) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	info, err := os.Stat(p)
	if err != nil || info.IsDir() {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "NOT_FILE"}})
		return
	}
	c.Header("X-Roami-File-Path", url.PathEscape(p))
	if c.Query("dl") != "" {
		serveAttachment(c, p, filepath.Base(p))
		return
	}
	f, err := os.Open(p)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "FS_ERROR", "message": err.Error()}})
		return
	}
	defer f.Close()

	// gin.Context.File 最终调用 http.ServeFile；当请求 URL 以 /index.html 结尾时，
	// ServeFile 会自动重定向到 ./。本接口的 ./ 是目录，而目录会被上面的校验拒绝，
	// 于是文件面板打开 index.html 时只能看到 NOT_FILE JSON。ServeContent 不做该重定向，
	// 同时仍保留按扩展名判断 Content-Type、Last-Modified 与 Range 请求支持。
	http.ServeContent(c.Writer, c.Request, filepath.Base(p), info.ModTime(), f)
}

var officePreviewExt = map[string]bool{
	".doc": true, ".docx": true, ".odt": true, ".rtf": true,
	".xls": true, ".xlsx": true, ".xlsm": true, ".ods": true,
	".ppt": true, ".pptx": true, ".odp": true,
}

// FilePreview GET /file/preview?path=<office-file> —— 使用本机 LibreOffice/soffice 转成 PDF 后内嵌预览。
func (a *API) FilePreview(c *gin.Context) {
	p := filepath.Clean(c.Query("path"))
	if p == "" || !filepath.IsAbs(p) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	info, err := os.Stat(p)
	if err != nil || info.IsDir() {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "NOT_FILE"}})
		return
	}
	if !officePreviewExt[strings.ToLower(filepath.Ext(p))] {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "UNSUPPORTED_PREVIEW", "message": "此文件类型不支持 Office 预览"}})
		return
	}
	soffice := findSoffice()
	if soffice == "" {
		c.JSON(http.StatusNotImplemented, gin.H{"error": gin.H{"code": "PREVIEW_UNAVAILABLE", "message": "未安装 LibreOffice/soffice，无法生成 Office 预览"}})
		return
	}
	tmp, err := os.MkdirTemp("", "ttmux-office-preview-*")
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "PREVIEW_ERROR", "message": err.Error()}})
		return
	}
	defer os.RemoveAll(tmp)

	ctx, cancel := context.WithTimeout(c.Request.Context(), 45*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, soffice, "--headless", "--nologo", "--nofirststartwizard", "--convert-to", "pdf", "--outdir", tmp, p)
	out, err := cmd.CombinedOutput()
	if ctx.Err() == context.DeadlineExceeded {
		c.JSON(http.StatusGatewayTimeout, gin.H{"error": gin.H{"code": "PREVIEW_TIMEOUT", "message": "Office 预览转换超时"}})
		return
	}
	if err != nil {
		msg := strings.TrimSpace(string(out))
		if msg == "" {
			msg = err.Error()
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "PREVIEW_ERROR", "message": msg}})
		return
	}
	pdfs, _ := filepath.Glob(filepath.Join(tmp, "*.pdf"))
	if len(pdfs) == 0 {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "PREVIEW_ERROR", "message": "转换完成但未生成 PDF"}})
		return
	}
	c.Header("Content-Type", "application/pdf")
	c.Header("Content-Disposition", contentDisposition("inline", strings.TrimSuffix(filepath.Base(p), filepath.Ext(p))+".pdf"))
	c.File(pdfs[0])
}

func findSoffice() string {
	for _, name := range []string{"libreoffice", "soffice"} {
		if p, err := exec.LookPath(name); err == nil {
			return p
		}
	}
	return ""
}

// ErrBadPath 表示下载路径为空或非绝对路径。抽出以便 HTTP 与 P2P 两处判定完全一致（评审点4）。
var ErrBadPath = errors.New("bad download path")

// ValidateDownloadPath 校验下载路径：Clean + 必须绝对 + 目标存在（Stat 成功）。
// 与 FileDownload 原有内联校验逐字节一致：路径空/非绝对 → ErrBadPath；Stat 失败 → 原始错误。
// HTTP 下载与 P2P serveFile 共用同一函数，保证两处权限完全一致（评审点4）。
func ValidateDownloadPath(raw string) (string, error) {
	p := filepath.Clean(raw)
	if p == "" || !filepath.IsAbs(p) {
		return "", ErrBadPath
	}
	if _, err := os.Stat(p); err != nil {
		return "", err
	}
	return p, nil
}

func serveAttachment(c *gin.Context, path, filename string) {
	c.Header("Content-Disposition", contentDisposition("attachment", filename))
	if ct := mime.TypeByExtension(filepath.Ext(filename)); ct != "" {
		c.Header("Content-Type", ct)
	}
	c.File(path)
}

func contentDisposition(kind, filename string) string {
	if filename == "" {
		filename = "download"
	}
	ascii := asciiFilename(filename)
	return fmt.Sprintf(`%s; filename="%s"; filename*=UTF-8''%s`, kind, ascii, urlPathEscape(filename))
}

func urlPathEscape(s string) string {
	return strings.ReplaceAll(url.PathEscape(s), "%2F", "_")
}

func asciiFilename(s string) string {
	var b strings.Builder
	for _, r := range s {
		if r < 32 || r == 127 || r == '\\' || r == '"' || r == '/' {
			b.WriteByte('_')
			continue
		}
		if r > 126 {
			b.WriteByte('_')
			continue
		}
		b.WriteRune(r)
	}
	out := strings.TrimSpace(b.String())
	if out == "" {
		return "download"
	}
	return out
}

// FileStat GET /file/stat?path=<file-or-dir> —— 判断路径是否存在以及返回基础元数据。
func (a *API) FileStat(c *gin.Context) {
	p := filepath.Clean(c.Query("path"))
	if p == "" || !filepath.IsAbs(p) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	info, err := os.Stat(p)
	if err != nil {
		if os.IsNotExist(err) {
			c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "NOT_FOUND", "message": "路径不存在"}})
			return
		}
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "FS_ERROR", "message": err.Error()}})
		return
	}
	stat := fileStatData{
		Path: p, Name: filepath.Base(p), Dir: info.IsDir(), Size: info.Size(),
		Mtime: info.ModTime().Unix(), Ctime: fileCtime(info), Mode: info.Mode().String(),
	}
	if info.IsDir() {
		if entries, err := os.ReadDir(p); err == nil {
			stat.EntryCount = len(entries)
		}
	}
	c.JSON(http.StatusOK, gin.H{"data": stat})
}

// FileRename POST /file/rename —— 在同一父目录内重命名文件或目录。
func (a *API) FileRename(c *gin.Context) {
	var req struct {
		Path string `json:"path"`
		Name string `json:"name"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_FORM", "message": err.Error()}})
		return
	}
	src := filepath.Clean(req.Path)
	if src == "" || !filepath.IsAbs(src) || src == string(filepath.Separator) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	if _, err := os.Lstat(src); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "FS_ERROR", "message": err.Error()}})
		return
	}
	name := cleanEntryName(req.Name)
	if name == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_NAME"}})
		return
	}
	dest := filepath.Join(filepath.Dir(src), name)
	if dest == src {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"path": dest}})
		return
	}
	if _, err := os.Lstat(dest); err == nil {
		c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "EXISTS"}})
		return
	}
	if err := os.Rename(src, dest); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "RENAME_ERROR", "message": err.Error()}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"path": dest}})
}

// FileCopy POST /file/copy —— 复制文件或目录到指定绝对路径。target 已存在且是目录时复制到目录内。
func (a *API) FileCopy(c *gin.Context) {
	var req struct {
		Path   string `json:"path"`
		Target string `json:"target"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_FORM", "message": err.Error()}})
		return
	}
	src := filepath.Clean(req.Path)
	target := filepath.Clean(req.Target)
	if src == "" || target == "" || !filepath.IsAbs(src) || !filepath.IsAbs(target) || src == string(filepath.Separator) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	info, err := os.Lstat(src)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "FS_ERROR", "message": err.Error()}})
		return
	}
	dest := target
	if ti, err := os.Stat(target); err == nil && ti.IsDir() {
		dest = filepath.Join(target, filepath.Base(src))
	}
	if dest == src {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "SAME_PATH"}})
		return
	}
	if info.IsDir() {
		if rel, err := filepath.Rel(src, dest); err == nil && (rel == "." || (!strings.HasPrefix(rel, "..") && rel != "")) {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "COPY_INTO_SELF"}})
			return
		}
	}
	if _, err := os.Lstat(dest); err == nil {
		c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "EXISTS"}})
		return
	}
	// 复制到 dest 旁的唯一临时名，成功后原子提交（不覆盖已存在目标）：
	// 失败清理只触及本次创建的临时对象，不会误删并发创建的 dest。
	tmpDest := fmt.Sprintf("%s.~copying-%d-%d", dest, os.Getpid(), time.Now().UnixNano())
	if err := copyPath(src, tmpDest); err != nil {
		_ = os.RemoveAll(tmpDest)
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "COPY_ERROR", "message": err.Error()}})
		return
	}
	if err := renameNoReplace(tmpDest, dest); err != nil {
		_ = os.RemoveAll(tmpDest)
		if os.IsExist(err) {
			c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "EXISTS"}})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "COPY_ERROR", "message": err.Error()}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"path": dest, "dir": info.IsDir()}})
}

// FileMove POST /file/move —— 移动文件或目录到指定绝对路径。target 已存在且是目录时移入目录内。
func (a *API) FileMove(c *gin.Context) {
	var req struct {
		Path   string `json:"path"`
		Target string `json:"target"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_FORM", "message": err.Error()}})
		return
	}
	src := filepath.Clean(req.Path)
	target := filepath.Clean(req.Target)
	if src == "" || target == "" || !filepath.IsAbs(src) || !filepath.IsAbs(target) || src == string(filepath.Separator) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	info, err := os.Lstat(src)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "FS_ERROR", "message": err.Error()}})
		return
	}
	dest := target
	if ti, err := os.Stat(target); err == nil && ti.IsDir() {
		dest = filepath.Join(target, filepath.Base(src))
	}
	if dest == src {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "SAME_PATH"}})
		return
	}
	if info.IsDir() {
		if rel, err := filepath.Rel(src, dest); err == nil && (rel == "." || (!strings.HasPrefix(rel, "..") && rel != "")) {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "MOVE_INTO_SELF"}})
			return
		}
	}
	if _, err := os.Lstat(dest); err == nil {
		c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "EXISTS"}})
		return
	}
	if err := renameNoReplace(src, dest); err != nil {
		if os.IsExist(err) {
			c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "EXISTS"}})
			return
		}
		// 跨设备(EXDEV)等 rename 失败时退化为 复制+删除。
		// 先把源原子改名到同目录临时名并校验 inode：复制/删除期间源路径若被并发替换，
		// 直接 copyPath(src)+RemoveAll(src) 会复制/删掉替换对象（TOCTOU）。
		tmp := fmt.Sprintf("%s.~moving-%d-%d", src, os.Getpid(), time.Now().UnixNano())
		if err := os.Rename(src, tmp); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "MOVE_ERROR", "message": err.Error()}})
			return
		}
		restoreSrc := func(failMsg string) bool {
			if rerr := renameNoReplace(tmp, src); rerr != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "RESTORE_ERROR", "message": failMsg + "，内容遗留在临时路径: " + tmp}})
				return false
			}
			return true
		}
		if st, err := os.Lstat(tmp); err != nil || !os.SameFile(info, st) {
			if restoreSrc("源被并发修改且还原失败") {
				c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "PATH_CHANGED", "message": "源在移动前被并发修改，未移动"}})
			}
			return
		}
		// 复制到 dest 旁的唯一临时名，成功后原子提交（不覆盖已存在目标）：
		// 失败清理只触及本次创建的临时对象，不会误删并发创建的 dest。
		tmpDest := fmt.Sprintf("%s.~moving-%d-%d", dest, os.Getpid(), time.Now().UnixNano())
		if cerr := copyPath(tmp, tmpDest); cerr != nil {
			_ = os.RemoveAll(tmpDest)
			if restoreSrc("复制失败且源还原失败") {
				c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "MOVE_ERROR", "message": cerr.Error()}})
			}
			return
		}
		if cerr := renameNoReplace(tmpDest, dest); cerr != nil {
			_ = os.RemoveAll(tmpDest)
			if restoreSrc("目标提交失败且源还原失败") {
				if os.IsExist(cerr) {
					c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "EXISTS"}})
				} else {
					c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "MOVE_ERROR", "message": cerr.Error()}})
				}
			}
			return
		}
		if rerr := os.RemoveAll(tmp); rerr != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "MOVE_ERROR", "message": "已移动到目标，但源清理失败，内容遗留在临时路径: " + tmp}})
			return
		}
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"path": dest, "dir": info.IsDir()}})
}

// FileTouch POST /file/touch —— 在指定目录(dir)下新建空文件(name)。返回创建后的绝对路径。
func (a *API) FileTouch(c *gin.Context) {
	var req struct {
		Dir  string `json:"dir"`
		Name string `json:"name"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_FORM", "message": err.Error()}})
		return
	}
	dir := filepath.Clean(req.Dir)
	if dir == "" || !filepath.IsAbs(dir) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	if info, err := os.Stat(dir); err != nil || !info.IsDir() {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "NOT_DIR"}})
		return
	}
	name := cleanEntryName(req.Name)
	if name == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_NAME"}})
		return
	}
	dest := filepath.Join(dir, name)
	f, err := os.OpenFile(dest, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
	if err != nil {
		if os.IsExist(err) {
			c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "EXISTS"}})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "WRITE_ERROR", "message": err.Error()}})
		return
	}
	_ = f.Close()
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"path": dest}})
}

// FileDownload GET /file/download?path=<file-or-dir> —— 下载文件；目录会流式打包为 Zip。
func (a *API) FileDownload(c *gin.Context) {
	p, err := ValidateDownloadPath(c.Query("path"))
	if err != nil {
		if errors.Is(err, ErrBadPath) {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
			return
		}
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "FS_ERROR", "message": err.Error()}})
		return
	}
	info, err := os.Stat(p)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "FS_ERROR", "message": err.Error()}})
		return
	}
	if !info.IsDir() {
		serveAttachment(c, p, filepath.Base(p))
		return
	}
	filename := filepath.Base(p)
	if filename == "." || filename == string(filepath.Separator) || filename == "" {
		filename = "download"
	}
	c.Header("Content-Disposition", contentDisposition("attachment", filename+".zip"))
	c.Header("Content-Type", "application/zip")
	zw := zip.NewWriter(c.Writer)
	defer zw.Close()
	base := filepath.Dir(p)
	_ = filepath.WalkDir(p, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if path == p {
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return nil
		}
		rel, err := filepath.Rel(base, path)
		if err != nil {
			return nil
		}
		rel = filepath.ToSlash(rel)
		if d.IsDir() {
			_, _ = zw.Create(rel + "/")
			return nil
		}
		h, err := zip.FileInfoHeader(info)
		if err != nil {
			return nil
		}
		h.Name = rel
		h.Method = zip.Deflate
		w, err := zw.CreateHeader(h)
		if err != nil {
			return nil
		}
		f, err := os.Open(path)
		if err != nil {
			return nil
		}
		_, _ = io.Copy(w, f)
		_ = f.Close()
		return nil
	})
}

// FileDelete DELETE /file?path=<path>[&recursive=1] —— 删除文件或目录；非空目录需 recursive=1。
func (a *API) FileDelete(c *gin.Context) {
	p := filepath.Clean(c.Query("path"))
	if p == "" || !filepath.IsAbs(p) || p == string(filepath.Separator) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	info, err := os.Lstat(p)
	if err != nil {
		if os.IsNotExist(err) {
			c.JSON(http.StatusOK, gin.H{"data": gin.H{"path": p, "missing": true}})
			return
		}
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "FS_ERROR", "message": err.Error()}})
		return
	}
	recursive := c.Query("recursive") == "1"
	if info.IsDir() && !recursive {
		entries, err := os.ReadDir(p)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "READ_ERROR", "message": err.Error()}})
			return
		}
		if len(entries) > 0 {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "DIR_NOT_EMPTY", "message": "目录非空，未删除"}})
			return
		}
	}
	if info.IsDir() && recursive {
		// 先原子改名到同目录下的临时名再递归删除：若 Lstat 之后目标被并发替换，
		// 直接 RemoveAll(p) 会误删替换目录（TOCTOU）；改名后用 inode 校验兜底。
		tmp := fmt.Sprintf("%s.~deleting-%d-%d", p, os.Getpid(), time.Now().UnixNano())
		if err := os.Rename(p, tmp); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "DELETE_ERROR", "message": err.Error()}})
			return
		}
		if st, err := os.Lstat(tmp); err != nil || !os.SameFile(info, st) {
			// 改名到的不是确认过的那个目录，还原现场；还原也失败时如实报告遗留位置
			if rerr := renameNoReplace(tmp, p); rerr != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "RESTORE_ERROR", "message": "目标被并发修改且还原失败，内容遗留在临时路径: " + tmp}})
				return
			}
			c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "PATH_CHANGED", "message": "目标在删除前被并发修改，未删除"}})
			return
		}
		if err := os.RemoveAll(tmp); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "DELETE_ERROR", "message": err.Error()}})
			return
		}
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"path": p, "dir": true}})
		return
	}
	if err := os.Remove(p); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "DELETE_ERROR", "message": err.Error()}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"path": p, "dir": info.IsDir()}})
}

// FileMkdir POST /file/mkdir —— 在指定目录(dir)下新建子目录(name)。返回创建后的绝对路径。
func (a *API) FileMkdir(c *gin.Context) {
	var req struct {
		Dir  string `json:"dir"`
		Name string `json:"name"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_FORM", "message": err.Error()}})
		return
	}
	dir := filepath.Clean(req.Dir)
	if dir == "" || !filepath.IsAbs(dir) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	if info, err := os.Stat(dir); err != nil || !info.IsDir() {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "NOT_DIR"}})
		return
	}
	name := filepath.Base(strings.TrimSpace(req.Name)) // 去掉任何路径成分，防穿越
	if name == "" || name == "." || name == ".." {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_NAME", "message": "目录名无效"}})
		return
	}
	dest := filepath.Join(dir, name)
	if _, err := os.Stat(dest); err == nil {
		c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "EXISTS", "message": "同名文件或目录已存在"}})
		return
	}
	if err := os.Mkdir(dest, 0o755); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "MKDIR_ERROR", "message": err.Error()}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"path": dest}})
}

func cleanEntryName(name string) string {
	name = strings.TrimSpace(name)
	if name == "" || strings.ContainsAny(name, `/\`) {
		return ""
	}
	base := filepath.Base(name)
	if base == "." || base == ".." || base != name {
		return ""
	}
	return base
}

func copyPath(src, dest string) error {
	info, err := os.Lstat(src)
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 {
		target, err := os.Readlink(src)
		if err != nil {
			return err
		}
		return os.Symlink(target, dest)
	}
	if info.IsDir() {
		if err := os.Mkdir(dest, info.Mode().Perm()); err != nil {
			return err
		}
		entries, err := os.ReadDir(src)
		if err != nil {
			return err
		}
		for _, e := range entries {
			if err := copyPath(filepath.Join(src, e.Name()), filepath.Join(dest, e.Name())); err != nil {
				return err
			}
		}
		return nil
	}
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.OpenFile(dest, os.O_WRONLY|os.O_CREATE|os.O_EXCL, info.Mode().Perm())
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		_ = out.Close()
		return err
	}
	return out.Close()
}

// renameNoReplaceFallback 先查目标再改名；存在竞态窗口，仅在系统不支持原子 no-replace 时使用。
func renameNoReplaceFallback(oldpath, newpath string) error {
	if _, err := os.Lstat(newpath); err == nil {
		return &os.LinkError{Op: "rename", Old: oldpath, New: newpath, Err: os.ErrExist}
	}
	return os.Rename(oldpath, newpath)
}

// uniquePath 目标已存在时在扩展名前加 (1)/(2)… 避免覆盖。
func uniquePath(p string) string {
	if _, err := os.Stat(p); os.IsNotExist(err) {
		return p
	}
	ext := filepath.Ext(p)
	base := strings.TrimSuffix(p, ext)
	for i := 1; ; i++ {
		cand := fmt.Sprintf("%s (%d)%s", base, i, ext)
		if _, err := os.Stat(cand); os.IsNotExist(err) {
			return cand
		}
	}
}

// Upload POST /upload —— multipart 上传文件到指定目录(dir)。
// form: dir=<绝对目录> + 一个或多个 files=<文件>。返回保存后的绝对路径。
func (a *API) Upload(c *gin.Context) {
	dir := filepath.Clean(c.PostForm("dir"))
	if dir == "" || !filepath.IsAbs(dir) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	if info, err := os.Stat(dir); err != nil || !info.IsDir() {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "NOT_DIR"}})
		return
	}
	form, err := c.MultipartForm()
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_FORM", "message": err.Error()}})
		return
	}
	files := form.File["files"]
	if len(files) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "NO_FILE"}})
		return
	}
	// paths[i] 与 files[i] 平行：上传文件夹时存相对路径(保留层级)，普通文件为空。
	// Go 的 multipart 会用 filepath.Base 抹掉 fh.Filename 的路径，故层级只能靠它传。
	paths := form.Value["paths"]
	saved := []string{}
	for i, fh := range files {
		name := fh.Filename
		if i < len(paths) && strings.TrimSpace(paths[i]) != "" {
			name = paths[i]
		}
		// 用 Clean("/"+name) 把任何 .. 折叠到根再去掉前导 /，杜绝路径穿越。
		rel := filepath.Clean("/" + filepath.ToSlash(name))
		rel = strings.TrimPrefix(rel, "/")
		if rel == "" || rel == "." {
			continue
		}
		dest := uniquePath(filepath.Join(dir, rel))
		// 双保险：清理后仍须落在 dir 之内
		if r, err := filepath.Rel(dir, dest); err != nil || r == ".." || strings.HasPrefix(r, ".."+string(os.PathSeparator)) {
			continue
		}
		if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "WRITE_ERROR", "message": err.Error()}})
			return
		}
		if err := c.SaveUploadedFile(fh, dest); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "WRITE_ERROR", "message": err.Error()}})
			return
		}
		saved = append(saved, dest)
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"dir": dir, "saved": saved}})
}
