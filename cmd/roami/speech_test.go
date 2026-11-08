package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func speechFixture(t *testing.T) (string, string, []byte) {
	t.Helper()
	root := t.TempDir()
	audio := make([]byte, 48)
	copy(audio, "RIFF")
	copy(audio[8:], "WAVEfmt ")
	path := filepath.Join(root, "fixture.wav")
	if err := os.WriteFile(path, audio, 0600); err != nil {
		t.Fatal(err)
	}
	return root, path, audio
}

func audioDigest(audio []byte) string {
	digest := sha256.Sum256(audio)
	return hex.EncodeToString(digest[:])
}

func TestSpeechCLIUsesSavedLoginAndExactAudioWithoutConfigurationWrites(t *testing.T) {
	home := t.TempDir()
	t.Setenv("ROAMI_HOME", home)
	root, path, audio := speechFixture(t)
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		cookie, err := r.Cookie("node-session")
		if err != nil || cookie.Value != "fixture" {
			t.Error("saved Node login was not reused")
		}
		if r.Method != http.MethodPost || r.URL.Path != "/api/speech/transcribe" {
			t.Error("unexpected speech request", r.Method, r.URL.Path)
		}
		file, header, err := r.FormFile("audio")
		if err != nil {
			t.Fatal(err)
		}
		defer file.Close()
		body, _ := io.ReadAll(file)
		if !bytes.Equal(body, audio) || header.Filename != "fixture.wav" || len(r.MultipartForm.Value) != 0 {
			t.Error("audio changed or provider overrides were supplied")
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(" {\"data\": {\"text\": \"fixture transcription\"}}\n"))
	}))
	defer server.Close()
	credentials := filepath.Join(home, "credentials", url.QueryEscape(server.URL)+".json")
	if err := os.MkdirAll(filepath.Dir(credentials), 0700); err != nil {
		t.Fatal(err)
	}
	stored, _ := json.Marshal(savedCookie{Origin: server.URL, Cookies: []*http.Cookie{{Name: "node-session", Value: "fixture", Path: "/"}}})
	if err := os.WriteFile(credentials, stored, 0600); err != nil {
		t.Fatal(err)
	}
	code := runSpeech([]string{"transcribe", "--file", path, "--file-root", root, "--expected-file-sha256", audioDigest(audio), "--server", server.URL, "--json"})
	if code != 0 || calls != 1 {
		t.Fatal("CLI did not perform exactly one authenticated request", code, calls)
	}
	after, _ := os.ReadFile(credentials)
	if !bytes.Equal(after, stored) {
		t.Fatal("saved login was modified")
	}
	if _, err := os.Stat(filepath.Join(home, "config.yaml")); !os.IsNotExist(err) {
		t.Fatal("explicit Node selection created configuration", err)
	}
}

func TestSpeechReceiptRetainsExactResponseAndInputDigest(t *testing.T) {
	t.Setenv("ROAMI_HOME", t.TempDir())
	_, _, audio := speechFixture(t)
	raw := " {\"data\": {\"text\": \"fixture\"}}\n"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Set-Cookie", "private=fixture")
		_, _ = w.Write([]byte(raw))
	}))
	defer server.Close()
	connection, err := connectAPI(server.URL)
	if err != nil {
		t.Fatal(err)
	}
	result, err := transcribeSpeech(connection, audio, "fixture.wav")
	if err != nil || result.Response.Body != raw || result.Response.SHA256 != audioDigest([]byte(raw)) || result.Input.SHA256 != audioDigest(audio) || result.Input.Bytes != len(audio) {
		t.Fatal("lost primary response or input identity", result, err)
	}
	encoded, _ := json.Marshal(result)
	if bytes.Contains(encoded, []byte("private=fixture")) {
		t.Fatal("receipt exposed an authentication header")
	}
}

func TestSpeechLocalAdmissionRejectsBeforeNetwork(t *testing.T) {
	t.Setenv("ROAMI_HOME", t.TempDir())
	root, path, audio := speechFixture(t)
	_, outsidePath, _ := speechFixture(t)
	link := filepath.Join(root, "escape.wav")
	if err := os.Symlink(outsidePath, link); err != nil {
		t.Fatal(err)
	}
	bad := filepath.Join(root, "wrong.wav")
	if err := os.WriteFile(bad, bytes.Repeat([]byte("x"), 48), 0600); err != nil {
		t.Fatal(err)
	}
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls++ }))
	defer server.Close()
	for _, test := range []struct{ file, hash string }{{path, strings.Repeat("0", 64)}, {outsidePath, audioDigest(audio)}, {link, audioDigest(audio)}, {bad, audioDigest(bytes.Repeat([]byte("x"), 48))}} {
		if code := runSpeech([]string{"transcribe", "--file", test.file, "--file-root", root, "--expected-file-sha256", test.hash, "--server", server.URL}); code == 0 {
			t.Fatal("invalid input accepted", test.file)
		}
	}
	if calls != 0 {
		t.Fatal("invalid local input reached Node")
	}
	if err := os.Truncate(path, speechAudioLimit+1); err != nil {
		t.Fatal(err)
	}
	if _, err := readSpeechAudio(path, root, audioDigest(audio)); err == nil {
		t.Fatal("oversized audio accepted")
	}
}

func TestSpeechFailureAndRedirectAreNotReplayed(t *testing.T) {
	t.Setenv("ROAMI_HOME", t.TempDir())
	_, _, audio := speechFixture(t)
	for _, status := range []int{http.StatusUnauthorized, http.StatusServiceUnavailable, http.StatusTemporaryRedirect} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				w.Header().Set("Content-Type", "application/json")
				w.Header().Set("Location", "/must-not-follow")
				w.WriteHeader(status)
				_, _ = w.Write([]byte(`{"error":"fixture failure"}`))
			}))
			defer server.Close()
			connection, err := connectAPI(server.URL)
			if err != nil {
				t.Fatal(err)
			}
			result, err := transcribeSpeech(connection, audio, "fixture.wav")
			if err == nil || calls != 1 || result.Response.Status != status || result.Response.Body != `{"error":"fixture failure"}` {
				t.Fatal("failure was lost or replayed", result, err, calls)
			}
		})
	}
}
