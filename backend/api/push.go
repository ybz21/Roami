package api

// Web Push：每个部署自己生成一对 VAPID 密钥（~/.roami/push/vapid.json），手机上的 PWA 把订阅
// 交给后端存着；有事时用密钥签名 POST 到订阅里的网关（Apple / Google / Mozilla 各家浏览器自带）。
// 不需要任何中心服务、不需要 FCM / APNs 账号——Roami 是给所有人自托管的（24 稿 §4）。

import (
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"

	webpush "github.com/SherClockHolmes/webpush-go"
	"github.com/gin-gonic/gin"
)

type pushDevice struct {
	Device string               `json:"device"` // 前端随机生成、存本地的设备 id；同 device 覆盖
	UA     string               `json:"ua,omitempty"`
	Sub    webpush.Subscription `json:"subscription"`
	At     int64                `json:"at"`
}

type PushStore struct {
	dir     string
	mu      sync.Mutex
	pub     string
	priv    string
	devices map[string]pushDevice
}

func NewPushStore(dataDir string) *PushStore {
	s := &PushStore{dir: filepath.Join(dataDir, "push"), devices: map[string]pushDevice{}}
	_ = os.MkdirAll(s.dir, 0o700)
	s.loadKeys()
	s.loadDevices()
	return s
}

func (s *PushStore) loadKeys() {
	f := filepath.Join(s.dir, "vapid.json")
	var k struct{ Public, Private string }
	if b, err := os.ReadFile(f); err == nil && json.Unmarshal(b, &k) == nil && k.Public != "" && k.Private != "" {
		s.pub, s.priv = k.Public, k.Private
		return
	}
	priv, pub, err := webpush.GenerateVAPIDKeys()
	if err != nil {
		log.Printf("⚠ push: 生成 VAPID 密钥失败: %v", err)
		return
	}
	s.pub, s.priv = pub, priv
	b, _ := json.MarshalIndent(struct{ Public, Private string }{pub, priv}, "", "  ")
	_ = os.WriteFile(f, b, 0o600)
}

func (s *PushStore) loadDevices() {
	b, err := os.ReadFile(filepath.Join(s.dir, "devices.json"))
	if err != nil {
		return
	}
	var list []pushDevice
	if json.Unmarshal(b, &list) == nil {
		for _, d := range list {
			if d.Device != "" && d.Sub.Endpoint != "" {
				s.devices[d.Device] = d
			}
		}
	}
}

// 调用方持锁
func (s *PushStore) save() {
	list := make([]pushDevice, 0, len(s.devices))
	for _, d := range s.devices {
		list = append(list, d)
	}
	b, _ := json.MarshalIndent(list, "", "  ")
	tmp := filepath.Join(s.dir, "devices.json.tmp")
	if os.WriteFile(tmp, b, 0o600) == nil {
		_ = os.Rename(tmp, filepath.Join(s.dir, "devices.json"))
	}
}

func (s *PushStore) Public() string { return s.pub }

func (s *PushStore) Count() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.devices)
}

// PushPayload 是发给 Service Worker 的 JSON：sw.js 按它画通知、决定按钮
type PushPayload struct {
	ID      int64    `json:"id"`
	Type    string   `json:"type"` // session.waiting | session.done | session.error
	Session string   `json:"session"`
	Label   string   `json:"label"`
	Title   string   `json:"title"`
	Body    string   `json:"body"`
	Actions []string `json:"actions,omitempty"` // 通知上的按钮：allow / deny；能确定是 y/n 或「1. Yes」时才给
	Badge   int      `json:"badge"`             // 需要你的条数
}

// Broadcast 发给全部设备；网关回 404 / 410 的订阅当场删掉（用户在手机上撤销了权限）。
// 每台设备并发发，网关慢也不拖住调用方。
func (s *PushStore) Broadcast(p PushPayload) {
	if s.priv == "" {
		return
	}
	body, _ := json.Marshal(p)
	s.mu.Lock()
	targets := make([]pushDevice, 0, len(s.devices))
	for _, d := range s.devices {
		targets = append(targets, d)
	}
	s.mu.Unlock()
	for _, d := range targets {
		go s.sendOne(d, body)
	}
}

func (s *PushStore) sendOne(d pushDevice, body []byte) {
	sub := d.Sub
	resp, err := webpush.SendNotification(body, &sub, &webpush.Options{
		Subscriber:      "mailto:roami@localhost",
		VAPIDPublicKey:  s.pub,
		VAPIDPrivateKey: s.priv,
		TTL:             600,
		Urgency:         webpush.UrgencyHigh,
	})
	if err != nil {
		log.Printf("push: %s 发送失败: %v", d.Device, err)
		return
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, resp.Body)
	if resp.StatusCode == http.StatusNotFound || resp.StatusCode == http.StatusGone {
		s.mu.Lock()
		delete(s.devices, d.Device)
		s.save()
		s.mu.Unlock()
		log.Printf("push: %s 订阅已失效（%d），删掉", d.Device, resp.StatusCode)
	} else if resp.StatusCode >= 300 {
		log.Printf("push: %s 网关回 %d", d.Device, resp.StatusCode)
	}
}

// GET /push/vapid
func (a *API) PushVAPID(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"publicKey": a.Push.Public(), "devices": a.Push.Count()}})
}

// POST /push/subscribe {device, ua, subscription}
func (a *API) PushSubscribe(c *gin.Context) {
	var b pushDevice
	if err := c.ShouldBindJSON(&b); err != nil || b.Device == "" || b.Sub.Endpoint == "" || b.Sub.Keys.P256dh == "" || b.Sub.Keys.Auth == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	b.At = time.Now().Unix()
	a.Push.mu.Lock()
	a.Push.devices[b.Device] = b
	a.Push.save()
	a.Push.mu.Unlock()
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true}})
}

// DELETE /push/subscribe {device}
func (a *API) PushUnsubscribe(c *gin.Context) {
	var b struct {
		Device string `json:"device"`
	}
	_ = c.ShouldBindJSON(&b)
	if b.Device == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	a.Push.mu.Lock()
	delete(a.Push.devices, b.Device)
	a.Push.save()
	a.Push.mu.Unlock()
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true}})
}

// POST /push/test：给自己所有设备发一条，验证链路（设置页那颗「发一条测试」）
func (a *API) PushTest(c *gin.Context) {
	a.Push.Broadcast(PushPayload{Type: "test", Title: "Roami", Body: "推送通了：这条是测试", Badge: a.Inbox.Unread()})
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"devices": a.Push.Count()}})
}
