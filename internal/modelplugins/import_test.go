package modelplugins

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func fixtureUploads(prefix string) []Upload {
	return []Upload{{prefix + "package.json", strings.NewReader(`{"name":"@test/provider","version":"1.0","main":"./opencode.mjs","exports":"./opencode2.mjs","magpie":{"maxConcurrency":1}}`)}, {prefix + "opencode.mjs", strings.NewReader(`export async function Provider(){return {}}`)}}
}
func archive(t *testing.T, files []Upload) []byte {
	t.Helper()
	var buf bytes.Buffer
	z := zip.NewWriter(&buf)
	for _, f := range files {
		w, err := z.Create(f.Path)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = io.Copy(w, f.Reader); err != nil {
			t.Fatal(err)
		}
	}
	if err := z.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}
func TestFolderAndZIPHaveSameImmutableIdentity(t *testing.T) {
	root := t.TempDir()
	folder, err := ImportFolder(root, fixtureUploads("provider/"))
	if err != nil {
		t.Fatal(err)
	}
	data := archive(t, fixtureUploads("provider/"))
	zipped, err := ImportZIP(root, bytes.NewReader(data), int64(len(data)))
	if err != nil {
		t.Fatal(err)
	}
	if folder != zipped || folder.Entry != "opencode.mjs" || folder.MaxConcurrency != 1 {
		t.Fatalf("unexpected package: %+v / %+v", folder, zipped)
	}
	info, err := os.Stat(filepath.Join(root, folder.ID, "package.json"))
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatalf("private package: %v %v", info, err)
	}
	var metadata Package
	b, _ := os.ReadFile(filepath.Join(root, folder.ID, ".roami-package.json"))
	if json.Unmarshal(b, &metadata) != nil || metadata != folder {
		t.Fatal("metadata mismatch")
	}
	entries, _ := os.ReadDir(root)
	if len(entries) != 1 {
		t.Fatal("staging leaked")
	}
}
func TestRejectUnsafeImports(t *testing.T) {
	for _, name := range []string{"../escape", "/absolute", "a/../../escape", "C:/escape", "a\\escape", "a//file", "a/./file", ".git/config", ".env", "dir/.env.local"} {
		t.Run(name, func(t *testing.T) {
			files := append(fixtureUploads(""), Upload{name, strings.NewReader("x")})
			if _, err := ImportFolder(t.TempDir(), files); err == nil {
				t.Fatal("accepted unsafe path")
			}
		})
	}
	for _, files := range [][]Upload{
		append(fixtureUploads(""), Upload{"package.json", strings.NewReader("{}")}),
		{{"package.json", strings.NewReader(`{"name":"test","main":"../evil.js"}`)}},
		{{"package.json", strings.NewReader(`{"name":"test","main":"missing.js"}`)}},
		fixtureUploads("one/two/"),
		append(fixtureUploads("wrapped/"), Upload{"README.md", strings.NewReader("outside")}),
	} {
		if _, err := ImportFolder(t.TempDir(), files); err == nil {
			t.Fatal("accepted ambiguous or invalid package")
		}
	}
}
func TestZIPRejectsSymlinksAndExpandedOversize(t *testing.T) {
	var buf bytes.Buffer
	z := zip.NewWriter(&buf)
	header := &zip.FileHeader{Name: "link"}
	header.SetMode(os.ModeSymlink | 0777)
	w, _ := z.CreateHeader(header)
	_, _ = w.Write([]byte("/etc/passwd"))
	_ = z.Close()
	if _, err := ImportZIP(t.TempDir(), bytes.NewReader(buf.Bytes()), int64(buf.Len())); err == nil {
		t.Fatal("accepted symlink")
	}
	oversized := append(fixtureUploads(""), Upload{"huge", io.LimitReader(zeroReader{}, MaxFileBytes+1)})
	if _, err := ImportFolder(t.TempDir(), oversized); err == nil {
		t.Fatal("accepted oversized file")
	}
}

type zeroReader struct{}

func (zeroReader) Read(b []byte) (int, error) { clear(b); return len(b), nil }

func TestImportIgnoresMacArchiveMetadataAndResolvesServerExports(t *testing.T) {
	files := []Upload{{"provider/package.json", strings.NewReader(`{"name":"provider","exports":{"./server":{"import":"./server.ts"},".":"./client.js"}}`)}, {"provider/server.ts", strings.NewReader("export const Plugin=async()=>({})")}, {"provider/client.js", strings.NewReader("export default {}")}, {"provider/.DS_Store", strings.NewReader("metadata")}, {"__MACOSX/provider/._server.ts", strings.NewReader("metadata")}}
	data := archive(t, files)
	pkg, err := ImportZIP(t.TempDir(), bytes.NewReader(data), int64(len(data)))
	if err != nil {
		t.Fatal(err)
	}
	if pkg.Entry != "server.ts" {
		t.Fatalf("wrong Magpie entry: %s", pkg.Entry)
	}
}
