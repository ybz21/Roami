package modelplugins

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func collectionFixture() []Upload {
	return []Upload{
		{"repository/package.json", strings.NewReader(`{"name":"workspace","workspaces":["packages/*"],"private":true}`)},
		{"repository/README.md", strings.NewReader("workspace documentation")},
		{"repository/.git/config", strings.NewReader("private metadata")},
		{"repository/.env.local", strings.NewReader("private settings")},
		{"repository/node_modules/dependency/package.json", strings.NewReader(`{"name":"dependency","main":"index.js"}`)},
		{"repository/node_modules/dependency/index.js", strings.NewReader("ignored")},
		{"repository/packages/first/package.json", strings.NewReader(`{"name":"first-plugin","main":"index.mjs"}`)},
		{"repository/packages/first/index.mjs", strings.NewReader("export const Plugin=async()=>({})")},
		{"repository/packages/second/package.json", strings.NewReader(`{"name":"second-plugin","main":"index.mjs"}`)},
		{"repository/packages/second/index.mjs", strings.NewReader("export const Plugin=async()=>({})")},
		{"repository/packages/broken/package.json", strings.NewReader(`{"name":"broken-plugin","main":"missing.mjs"}`)},
	}
}
func TestImportCollectionFindsWorkspacePluginsAndKeepsSinglePackageIdentity(t *testing.T) {
	root := t.TempDir()
	folder, err := ImportCollectionFolder(root, collectionFixture())
	if err != nil || len(folder.Packages) != 2 || len(folder.Skipped) != 1 {
		t.Fatalf("%+v %v", folder, err)
	}
	archive := archive(t, collectionFixture())
	zipped, err := ImportCollectionZIP(root, bytes.NewReader(archive), int64(len(archive)))
	if err != nil || len(zipped.Packages) != 2 || zipped.Packages[0] != folder.Packages[0] || zipped.Packages[1] != folder.Packages[1] {
		t.Fatalf("different import: %+v %v", zipped, err)
	}
	single, err := ImportFolder(root, []Upload{{"package.json", strings.NewReader(`{"name":"first-plugin","main":"index.mjs"}`)}, {"index.mjs", strings.NewReader("export const Plugin=async()=>({})")}})
	if err != nil || single != folder.Packages[0] {
		t.Fatalf("identity changed: %+v %v", single, err)
	}
	for _, pkg := range folder.Packages {
		entries, err := os.ReadDir(filepath.Join(root, pkg.ID))
		if err != nil || len(entries) != 3 {
			t.Fatalf("workspace files leaked: %v %v", entries, err)
		}
	}
}
func TestImportCollectionRejectsUnsafeArchiveBeforePublishingAnyPackage(t *testing.T) {
	for _, name := range []string{"../escape", "repository/../escape", "repository/.git/../../escape", "repository/packages/first/.roami-package.json"} {
		root := t.TempDir()
		files := append(collectionFixture(), Upload{name, strings.NewReader("bad")})
		data := archive(t, files)
		if _, err := ImportCollectionZIP(root, bytes.NewReader(data), int64(len(data))); err == nil {
			t.Fatal("accepted", name)
		}
		entries, _ := os.ReadDir(root)
		if len(entries) != 0 {
			t.Fatal("partially published unsafe upload")
		}
	}
}
func TestImportCollectionHandlesNestedAndDuplicatePlugins(t *testing.T) {
	files := []Upload{{"bundle/a/package.json", strings.NewReader(`{"name":"parent","main":"index.mjs"}`)}, {"bundle/a/index.mjs", strings.NewReader("export const Plugin=async()=>({})")}, {"bundle/a/nested/package.json", strings.NewReader(`{"name":"child","main":"index.mjs"}`)}, {"bundle/a/nested/index.mjs", strings.NewReader("export const Child=async()=>({})")}, {"bundle/copy/package.json", strings.NewReader(`{"name":"child","main":"index.mjs"}`)}, {"bundle/copy/index.mjs", strings.NewReader("export const Child=async()=>({})")}}
	root := t.TempDir()
	result, err := ImportCollectionFolder(root, files)
	if err != nil || len(result.Packages) != 2 {
		t.Fatalf("%+v %v", result, err)
	}
	for _, pkg := range result.Packages {
		if _, err := os.Stat(filepath.Join(root, pkg.ID, "nested")); !os.IsNotExist(err) {
			t.Fatal("nested plugin copied into parent")
		}
	}
}
func TestImportCollectionRetainsAggregateLimits(t *testing.T) {
	files := append(collectionFixture(), Upload{"repository/large", io.LimitReader(zeroReader{}, MaxFileBytes+1)})
	if _, err := ImportCollectionFolder(t.TempDir(), files); err == nil {
		t.Fatal("accepted oversized collection file")
	}
}

func TestOfficialRepositoryCollectionPreservesIndividualPackages(t *testing.T) {
	source := os.Getenv("ROAMI_MAGPIE_FIXTURES")
	if source == "" {
		t.Skip("set ROAMI_MAGPIE_FIXTURES to verify the pinned repository")
	}
	var uploads []Upload
	repo := filepath.Dir(source)
	err := filepath.WalkDir(repo, func(filename string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		relative, _ := filepath.Rel(repo, filename)
		relative = filepath.ToSlash(relative)
		if collectionMetadata(relative) {
			if entry.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if entry.IsDir() {
			return nil
		}
		if entry.Type()&os.ModeSymlink != 0 {
			return ErrInvalidPackage
		}
		data, err := os.ReadFile(filename)
		if err != nil {
			return err
		}
		uploads = append(uploads, Upload{relative, bytes.NewReader(data)})
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	collection, err := ImportCollectionFolder(root, uploads)
	if err != nil || len(collection.Packages) < 2 {
		t.Fatalf("official collection: %+v %v", collection, err)
	}
	for _, name := range []string{"workbuddy", "doubao-work"} {
		var single []Upload
		err := filepath.WalkDir(filepath.Join(source, name), func(filename string, entry os.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if entry.IsDir() {
				return nil
			}
			rel, _ := filepath.Rel(filepath.Join(source, name), filename)
			data, err := os.ReadFile(filename)
			if err != nil {
				return err
			}
			single = append(single, Upload{filepath.ToSlash(rel), bytes.NewReader(data)})
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
		individual, err := ImportFolder(root, single)
		if err != nil {
			t.Fatal(err)
		}
		found := false
		for _, pkg := range collection.Packages {
			if pkg == individual {
				found = true
			}
		}
		if !found {
			t.Fatalf("individual identity changed for %s", name)
		}
	}
}
