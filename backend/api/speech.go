// 语音识别(ASR)：接收前端录音(WAV)，转发到所配置的服务商并返回识别文本。
// 火山 API Key 使用豆包流式识别 2.0；旧版双凭据保留录音文件识别兼容。
//
// 服务商密钥持久化到 <dataDir>/speech-config.json，单独管理，不走 env(避免被 push 进 shell 会话)。
package api

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

// 单个会话录音的体积上限(WAV 16k 单声道约 32KB/s，25MB 足够长语音)。
const speechMaxBytes = 25 << 20

type OpenAISpeech struct {
	BaseURL  string `json:"baseURL"`  // 默认 https://api.openai.com/v1
	APIKey   string `json:"apiKey"`   //
	Model    string `json:"model"`    // 默认 whisper-1
	Language string `json:"language"` // 可空：如 zh / en，留空自动检测
}

type VolcanoSpeech struct {
	APIKey      string `json:"apiKey"`      // 新版流式识别鉴权，优先于旧凭据
	AppID       string `json:"appId"`       // 旧版控制台 App ID
	AccessToken string `json:"accessToken"` // 火山控制台 Access Token
	ResourceID  string `json:"resourceId"`  // 默认 volc.bigasr.auc(大模型录音识别·标准版)；含 _turbo 走极速版
	Endpoint    string `json:"endpoint"`    // 默认标准版 submit 接口(极速版用 recognize/flash)
}

type SpeechConfig struct {
	Provider string        `json:"provider"` // "openai" | "volcano" | ""(未配置)
	OpenAI   OpenAISpeech  `json:"openai"`
	Volcano  VolcanoSpeech `json:"volcano"`
}

// SpeechStore 持久化 ASR 配置，原子写回。
type SpeechStore struct {
	file string
	mu   sync.Mutex
}

func NewSpeechStore(dataDir string) *SpeechStore {
	_ = os.MkdirAll(dataDir, 0o755)
	return &SpeechStore{file: filepath.Join(dataDir, "speech-config.json")}
}

func (s *SpeechStore) get() SpeechConfig {
	s.mu.Lock()
	defer s.mu.Unlock()
	var c SpeechConfig
	if b, err := os.ReadFile(s.file); err == nil {
		_ = json.Unmarshal(b, &c)
	}
	return c
}

func (s *SpeechStore) set(c SpeechConfig) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	b, _ := json.MarshalIndent(c, "", "  ")
	tmp := s.file + ".tmp"
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, s.file)
}

// GetSpeechConfig 返回当前 ASR 配置(含密钥；本工具单用户自托管，与 env 页一致地明文回显)。
func (a *API) GetSpeechConfig(c *gin.Context) {
	if a.Speech == nil {
		c.JSON(http.StatusOK, gin.H{"data": SpeechConfig{}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": a.Speech.get()})
}

// SetSpeechConfig 整体覆盖保存 ASR 配置。
func (a *API) SetSpeechConfig(c *gin.Context) {
	if a.Speech == nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "NO_STORE"}})
		return
	}
	var in SpeechConfig
	if err := c.ShouldBindJSON(&in); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	if err := a.Speech.set(in); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "WRITE_ERROR", "message": err.Error()}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true}})
}

// SpeechTranscribe 接收 multipart 字段 audio(WAV)，调所配置的服务商返回识别文本。
func (a *API) SpeechTranscribe(c *gin.Context) {
	if a.Speech == nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "NO_STORE"}})
		return
	}
	cfg := a.Speech.get()
	fh, err := c.FormFile("audio")
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "NO_AUDIO"}})
		return
	}
	if fh.Size > speechMaxBytes {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "AUDIO_TOO_LARGE"}})
		return
	}
	f, err := fh.Open()
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_AUDIO", "message": err.Error()}})
		return
	}
	defer f.Close()
	audio, err := io.ReadAll(io.LimitReader(f, speechMaxBytes))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_AUDIO", "message": err.Error()}})
		return
	}

	// 诊断：记录上传音频体积/时长/峰值响度，便于判断「识别空」是客户端录到静音还是服务端没认出。
	peak, durSec := wavStats(audio)
	log.Printf("[speech] upload provider=%s name=%q bytes=%d dur=%.1fs peak=%.3f", cfg.Provider, fh.Filename, len(audio), durSec, peak)

	var text string
	switch cfg.Provider {
	case "openai":
		text, err = transcribeOpenAI(cfg.OpenAI, audio, fh.Filename)
	case "volcano":
		text, err = transcribeVolcano(c.Request.Context(), cfg.Volcano, audio)
	default:
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "NOT_CONFIGURED"}})
		return
	}
	if err != nil {
		log.Printf("[speech] asr error: %v", err)
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"code": "ASR_ERROR", "message": err.Error()}})
		return
	}
	log.Printf("[speech] result text=%q", strings.TrimSpace(text))
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"text": strings.TrimSpace(text)}})
}

// transcribeOpenAI 走 OpenAI 兼容的 /audio/transcriptions multipart 接口。
func transcribeOpenAI(cfg OpenAISpeech, audio []byte, filename string) (string, error) {
	if cfg.APIKey == "" {
		return "", fmt.Errorf("openai api key not set")
	}
	base := strings.TrimRight(cfg.BaseURL, "/")
	if base == "" {
		base = "https://api.openai.com/v1"
	}
	model := cfg.Model
	if model == "" {
		model = "whisper-1"
	}
	if filename == "" {
		filename = "audio.wav"
	}

	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	fw, err := w.CreateFormFile("file", filename)
	if err != nil {
		return "", err
	}
	if _, err := fw.Write(audio); err != nil {
		return "", err
	}
	_ = w.WriteField("model", model)
	if cfg.Language != "" {
		_ = w.WriteField("language", cfg.Language)
	}
	if err := w.Close(); err != nil {
		return "", err
	}

	req, err := http.NewRequest("POST", base+"/audio/transcriptions", &buf)
	if err != nil {
		return "", err
	}
	req.Header.Set("Authorization", "Bearer "+cfg.APIKey)
	req.Header.Set("Content-Type", w.FormDataContentType())

	resp, err := (&http.Client{Timeout: 120 * time.Second}).Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("openai %d: %s", resp.StatusCode, truncate(string(body), 300))
	}
	var r struct {
		Text  string `json:"text"`
		Error *struct {
			Message string `json:"message"`
		} `json:"error"`
	}
	if err := json.Unmarshal(body, &r); err != nil {
		return "", fmt.Errorf("parse openai resp: %w", err)
	}
	if r.Error != nil {
		return "", fmt.Errorf("openai: %s", r.Error.Message)
	}
	return r.Text, nil
}

// 火山大模型识别请求体(标准版 submit / 极速版 flash 同构)：音频以 base64 放进 JSON。
func volcanoReqBody(audio []byte) []byte {
	b, _ := json.Marshal(map[string]any{
		"user": map[string]any{"uid": "ttmux"},
		"audio": map[string]any{
			"format": "wav",
			"data":   base64.StdEncoding.EncodeToString(audio),
		},
		"request": map[string]any{
			"model_name":  "bigmodel",
			"enable_itn":  true,
			"enable_punc": true,
		},
	})
	return b
}

// volcanoPost 发一次火山接口调用，返回状态码头(X-Api-Status-Code)、消息头与响应体。
// 鉴权统一用请求头携带 App Key / Access Key / Resource Id；同一 reqID 用于 submit→query 关联。
func volcanoPost(client *http.Client, url string, cfg VolcanoSpeech, resourceID, reqID string, payload []byte) (code, msg string, body []byte, err error) {
	req, err := http.NewRequest("POST", url, bytes.NewReader(payload))
	if err != nil {
		return "", "", nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	// 新版控制台只有一个 API Key（X-Api-Key）；旧版是 App ID + Access Token 两个头。其余头两版相同
	if cfg.APIKey != "" {
		req.Header.Set("X-Api-Key", cfg.APIKey)
	} else {
		req.Header.Set("X-Api-App-Key", cfg.AppID)
		req.Header.Set("X-Api-Access-Key", cfg.AccessToken)
	}
	req.Header.Set("X-Api-Resource-Id", resourceID)
	req.Header.Set("X-Api-Request-Id", reqID)
	req.Header.Set("X-Api-Sequence", "-1")
	resp, err := client.Do(req)
	if err != nil {
		return "", "", nil, err
	}
	defer resp.Body.Close()
	body, _ = io.ReadAll(resp.Body)
	return resp.Header.Get("X-Api-Status-Code"), resp.Header.Get("X-Api-Message"), body, nil
}

// volcanoText 解析识别结果体 {"result":{"text":"..."}}（标准版与极速版同构）。
func volcanoText(body []byte) (string, error) {
	var r struct {
		Result struct {
			Text string `json:"text"`
		} `json:"result"`
	}
	if err := json.Unmarshal(body, &r); err != nil {
		return "", fmt.Errorf("parse volcano resp: %w", err)
	}
	return r.Result.Text, nil
}

func transcribeVolcano(ctx context.Context, cfg VolcanoSpeech, audio []byte) (string, error) {
	if strings.TrimSpace(cfg.APIKey) != "" {
		return transcribeVolcanoStream(ctx, cfg, audio)
	}
	if cfg.AppID == "" || cfg.AccessToken == "" {
		return "", fmt.Errorf("volcano credentials not set")
	}
	resourceID := cfg.ResourceID
	if resourceID == "" {
		resourceID = "volc.bigasr.auc"
	}
	if strings.Contains(resourceID, "turbo") {
		return transcribeVolcanoFlash(cfg, resourceID, audio)
	}
	return transcribeVolcanoStandard(cfg, resourceID, audio)
}

// transcribeVolcanoStandard 走标准版：先 submit 提交任务，再轮询 query 拿结果。
// 状态码在响应头：20000000 成功、20000003 静音/无语音(终态，文本为空)、
// 20000001/20000002 处理中/排队中(继续轮询)，其余按错误处理。
func transcribeVolcanoStandard(cfg VolcanoSpeech, resourceID string, audio []byte) (string, error) {
	submitURL := cfg.Endpoint
	if submitURL == "" {
		submitURL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
	}
	queryURL := strings.TrimSuffix(submitURL, "/submit") + "/query"
	reqID := randomID()
	client := &http.Client{Timeout: 30 * time.Second}

	code, msg, body, err := volcanoPost(client, submitURL, cfg, resourceID, reqID, volcanoReqBody(audio))
	if err != nil {
		return "", err
	}
	if code != "" && code != "20000000" {
		return "", fmt.Errorf("volcano submit %s: %s %s", code, msg, truncate(string(body), 200))
	}

	// 轮询 query：标准版异步，识别完成才返回终态码。最长约 30s。
	for i := 0; i < 50; i++ {
		time.Sleep(600 * time.Millisecond)
		code, msg, body, err = volcanoPost(client, queryURL, cfg, resourceID, reqID, []byte("{}"))
		if err != nil {
			return "", err
		}
		switch code {
		case "20000000", "20000003": // 完成(有文本 / 静音空文本)
			return volcanoText(body)
		case "20000001", "20000002", "": // 处理中 / 排队中
			continue
		default:
			return "", fmt.Errorf("volcano query %s: %s %s", code, msg, truncate(string(body), 200))
		}
	}
	return "", fmt.Errorf("volcano query timeout")
}

// transcribeVolcanoFlash 走极速版「大模型录音识别·极速版」(v3 flash) 一次性同步接口。
func transcribeVolcanoFlash(cfg VolcanoSpeech, resourceID string, audio []byte) (string, error) {
	endpoint := cfg.Endpoint
	if endpoint == "" {
		endpoint = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"
	}
	client := &http.Client{Timeout: 120 * time.Second}
	code, msg, body, err := volcanoPost(client, endpoint, cfg, resourceID, randomID(), volcanoReqBody(audio))
	if err != nil {
		return "", err
	}
	// 极速版成功/失败码放在响应头(20000000 表示成功)。
	if code != "" && code != "20000000" {
		return "", fmt.Errorf("volcano %s: %s %s", code, msg, truncate(string(body), 200))
	}
	return volcanoText(body)
}

// wavStats 估算 16k 单声道 16bit PCM WAV 的峰值响度(0~1)与时长(秒)，用于诊断静音上传。
func wavStats(b []byte) (peak float64, durSec float64) {
	if len(b) <= 44 {
		return 0, 0
	}
	pcm := b[44:]
	mx := 0
	for i := 0; i+1 < len(pcm); i += 2 {
		s := int(int16(uint16(pcm[i]) | uint16(pcm[i+1])<<8))
		if s < 0 {
			s = -s
		}
		if s > mx {
			mx = s
		}
	}
	return float64(mx) / 32768.0, float64(len(pcm)/2) / 16000.0
}

func randomID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "ttmux-req"
	}
	return hex.EncodeToString(b[:])
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}
