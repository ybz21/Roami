package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const speechAudioLimit = 25 << 20

type speechReceipt struct {
	Data  json.RawMessage `json:"data,omitempty"`
	Error any             `json:"error,omitempty"`
	Input struct {
		SHA256 string `json:"sha256"`
		Bytes  int    `json:"bytes"`
	} `json:"input"`
	Response struct {
		Status      int    `json:"status"`
		ContentType string `json:"contentType"`
		SHA256      string `json:"sha256"`
		Body        string `json:"body"`
		Truncated   bool   `json:"truncated,omitempty"`
	} `json:"response"`
}

func readSpeechAudio(file, root, expected string) ([]byte, error) {
	if file == "" || root == "" || len(expected) != 64 {
		return nil, fmt.Errorf("--file, --file-root and a lowercase --expected-file-sha256 are required")
	}
	if _, err := hex.DecodeString(expected); err != nil || expected != strings.ToLower(expected) {
		return nil, fmt.Errorf("invalid expected SHA-256")
	}
	base, err := filepath.EvalSymlinks(root)
	if err != nil {
		return nil, err
	}
	base, err = filepath.Abs(base)
	if err != nil {
		return nil, err
	}
	info, err := os.Stat(base)
	if err != nil || !info.IsDir() {
		return nil, fmt.Errorf("file root must be an existing directory")
	}
	path, err := filepath.EvalSymlinks(file)
	if err != nil {
		return nil, err
	}
	path, err = filepath.Abs(path)
	if err != nil {
		return nil, err
	}
	relative, err := filepath.Rel(base, path)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) || filepath.IsAbs(relative) {
		return nil, fmt.Errorf("audio is outside the selected file root")
	}
	info, err = os.Stat(path)
	if err != nil || !info.Mode().IsRegular() {
		return nil, fmt.Errorf("audio must be a regular file")
	}
	stream, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer stream.Close()
	info, err = stream.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Size() > speechAudioLimit {
		return nil, fmt.Errorf("audio must be a regular WAV file of at most 25 MiB")
	}
	audio, err := io.ReadAll(io.LimitReader(stream, speechAudioLimit+1))
	if err != nil {
		return nil, err
	}
	if len(audio) > speechAudioLimit || len(audio) < 44 || string(audio[:4]) != "RIFF" || string(audio[8:12]) != "WAVE" || !strings.EqualFold(filepath.Ext(path), ".wav") {
		return nil, fmt.Errorf("expected a WAV audio file of at most 25 MiB; derive it from the final media and preserve the conversion evidence")
	}
	digest := sha256.Sum256(audio)
	if hex.EncodeToString(digest[:]) != expected {
		return nil, fmt.Errorf("audio differs from the expected SHA-256")
	}
	return audio, nil
}

func transcribeSpeech(connection *apiConnection, audio []byte, filename string) (speechReceipt, error) {
	result := speechReceipt{}
	digest := sha256.Sum256(audio)
	result.Input.SHA256, result.Input.Bytes = hex.EncodeToString(digest[:]), len(audio)
	var body bytes.Buffer
	form := multipart.NewWriter(&body)
	part, err := form.CreateFormFile("audio", filepath.Base(filename))
	if err != nil {
		return result, err
	}
	if _, err := part.Write(audio); err != nil {
		return result, err
	}
	if err := form.Close(); err != nil {
		return result, err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, connection.origin+"/api/speech/transcribe", &body)
	if err != nil {
		return result, err
	}
	request.Header.Set("Content-Type", form.FormDataContentType())
	connection.client.Timeout = 2 * time.Minute
	response, err := connection.client.Do(request)
	if err != nil {
		return result, fmt.Errorf("transcription outcome unavailable; no automatic retry: %w", err)
	}
	defer response.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(response.Body, (1<<20)+1))
	if err != nil {
		return result, err
	}
	result.Response.Status, result.Response.ContentType = response.StatusCode, response.Header.Get("Content-Type")
	result.Response.Body = string(raw)
	digest = sha256.Sum256(raw)
	result.Response.SHA256 = hex.EncodeToString(digest[:])
	if len(raw) > 1<<20 {
		result.Response.Truncated = true
		return result, fmt.Errorf("transcription response exceeds 1 MiB")
	}
	if response.StatusCode == http.StatusUnauthorized {
		return result, fmt.Errorf("Node login required; run roami auth login; request was not retried")
	}
	if response.StatusCode != http.StatusOK {
		return result, fmt.Errorf("transcription failed with HTTP %d; request was not retried", response.StatusCode)
	}
	var payload struct {
		Data json.RawMessage `json:"data"`
	}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return result, fmt.Errorf("Node returned an invalid transcription response")
	}
	var text struct {
		Text *string `json:"text"`
	}
	if err := json.Unmarshal(payload.Data, &text); err != nil || text.Text == nil {
		return result, fmt.Errorf("Node returned no transcription text")
	}
	result.Data = payload.Data
	return result, nil
}

func runSpeech(args []string) int {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" || args[0] == "-h" {
		_ = groupHelpPage("speech").Render(os.Stdout)
		return 0
	}
	if args[0] != "transcribe" {
		fmt.Fprintln(os.Stderr, "unknown speech command; run roami speech help")
		return 2
	}
	fs := newCommandFlags("speech transcribe")
	file := fs.String("file", "", "selected WAV file")
	root := fs.String("file-root", "", "allowed local audio directory")
	expected := fs.String("expected-file-sha256", "", "expected audio digest")
	server := fs.String("server", "", "Roami Node origin")
	asJSON := fs.Bool("json", false, "return transcription and evidence as JSON")
	if err := fs.Parse(args[1:]); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return 0
		}
		return 2
	}
	if fs.NArg() != 0 {
		return 2
	}
	audio, err := readSpeechAudio(*file, *root, *expected)
	result := speechReceipt{}
	if err == nil {
		var connection *apiConnection
		connection, err = connectAPI(*server)
		if err == nil {
			result, err = transcribeSpeech(connection, audio, *file)
		}
	}
	if err != nil {
		result.Error = map[string]string{"code": "SPEECH_TRANSCRIPTION_FAILED", "message": err.Error()}
	}
	if *asJSON {
		encoded, _ := json.Marshal(result)
		fmt.Println(string(encoded))
	} else if err != nil {
		fmt.Fprintln(os.Stderr, err)
	} else {
		var text struct{ Text string }
		_ = json.Unmarshal(result.Data, &text)
		fmt.Println(text.Text)
	}
	if err != nil {
		return 1
	}
	return 0
}
