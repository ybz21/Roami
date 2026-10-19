// Package auth 负责口令校验、token 签发/校验、防爆破与认证中间件。
//
// 当前为单用户：口令来自配置（明文比较，常量时间）。argon2 哈希 +
// passwd 子命令 + TOTP/Passkey 为后续增强（见 docs/design/web/03-auth-security.md）。
package auth

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

const CookieName = "ttmux_session"

type Auth struct {
	secret    []byte
	statePath string // 两步验证状态持久化文件（开关 + 密钥）
	lockAfter int
	lockSecs  int
	ttl       time.Duration
	savePW    func(string) error // 把口令落盘到 config.yaml（首次设置/改密）

	mu          sync.Mutex
	password    string // 登录口令（明文，常量时间比较）；为空表示尚未设置，需首次设置
	totpSecret  string // 两步验证密钥（base32）
	totpOn      bool   // 是否启用两步验证（UI 可切换，持久化）
	fails       int
	lockedUntil time.Time
}

func New(password, totpSecret, statePath string, lockAfter, lockSecs int, savePW func(string) error) *Auth {
	a := &Auth{
		password:  password,
		secret:    randBytes(32),
		statePath: statePath,
		lockAfter: lockAfter,
		lockSecs:  lockSecs,
		ttl:       7 * 24 * time.Hour,
		savePW:    savePW,
	}
	// 初始种子来自环境变量；若存在状态文件（UI 曾操作过）则以文件为准
	a.totpSecret = strings.TrimSpace(totpSecret)
	a.totpOn = a.totpSecret != ""
	a.loadState()
	return a
}

type totpState struct {
	Secret string `json:"secret"`
	On     bool   `json:"on"`
}

func (a *Auth) loadState() {
	if a.statePath == "" {
		return
	}
	b, err := os.ReadFile(a.statePath)
	if err != nil {
		return
	}
	var s totpState
	if json.Unmarshal(b, &s) == nil {
		a.totpSecret = strings.TrimSpace(s.Secret)
		a.totpOn = s.On
	}
}

func (a *Auth) saveState() {
	if a.statePath == "" {
		return
	}
	a.mu.Lock()
	b, _ := json.Marshal(totpState{Secret: a.totpSecret, On: a.totpOn})
	a.mu.Unlock()
	_ = os.MkdirAll(filepath.Dir(a.statePath), 0o700)
	_ = os.WriteFile(a.statePath, b, 0o600)
}

// TOTPEnabled 是否启用两步验证。
func (a *Auth) TOTPEnabled() bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.totpOn && a.totpSecret != ""
}

// verifyCode 校验动态码；未启用两步验证时直接放行。
func (a *Auth) verifyCode(code string) bool {
	a.mu.Lock()
	on, s := a.totpOn, a.totpSecret
	a.mu.Unlock()
	if !on || s == "" {
		return true
	}
	return verifyTOTP(s, code)
}

func randBytes(n int) []byte {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		return []byte(time.Now().String())
	}
	return b
}

func (a *Auth) hmacHex(msg string) string {
	m := hmac.New(sha256.New, a.secret)
	m.Write([]byte(msg))
	return hex.EncodeToString(m.Sum(nil))
}

func (a *Auth) issue() string {
	exp := time.Now().Add(a.ttl).Unix()
	msg := fmt.Sprintf("%d.%s", exp, hex.EncodeToString(randBytes(8)))
	return msg + "." + a.hmacHex(msg)
}

func (a *Auth) verify(tok string) bool {
	p := strings.Split(tok, ".")
	if len(p) != 3 {
		return false
	}
	msg := p[0] + "." + p[1]
	if !hmac.Equal([]byte(a.hmacHex(msg)), []byte(p[2])) {
		return false
	}
	exp, err := strconv.ParseInt(p[0], 10, 64)
	return err == nil && time.Now().Unix() < exp
}

// Middleware 校验签名 Cookie；失败返回 401。
func (a *Auth) Middleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		// 来自已认证隧道的进程内请求（中心 已校验用户会话）直接放行，
		// 不要求节点本地登录 Cookie。标记走 request context，不可经线缆伪造。见 auth/internal.go。
		if IsInternal(c.Request) {
			c.Next()
			return
		}
		tok, err := c.Cookie(CookieName)
		if err != nil || !a.verify(tok) {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": gin.H{"code": "UNAUTHORIZED"}})
			return
		}
		c.Next()
	}
}

func (a *Auth) Login(c *gin.Context) {
	a.mu.Lock()
	locked := time.Now().Before(a.lockedUntil)
	a.mu.Unlock()
	if locked {
		c.JSON(http.StatusTooManyRequests, gin.H{"error": gin.H{"code": "LOCKED", "message": "登录已锁定，请稍后再试"}})
		return
	}

	var body struct {
		Password string `json:"password"`
		Code     string `json:"code"` // 两步验证动态码（启用时必填）
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}

	a.mu.Lock()
	cur := a.password
	a.mu.Unlock()
	pwOK := cur != "" && subtle.ConstantTimeCompare([]byte(body.Password), []byte(cur)) == 1
	// 口令对了但开启了两步验证 → 还要校验动态码
	codeOK := a.verifyCode(body.Code)

	if !pwOK || !codeOK {
		a.mu.Lock()
		a.fails++
		fails := a.fails
		if a.fails >= a.lockAfter {
			a.lockedUntil = time.Now().Add(time.Duration(a.lockSecs) * time.Second)
			a.fails = 0
		}
		a.mu.Unlock()
		backoff := fails
		if backoff > 3 {
			backoff = 3
		}
		time.Sleep(time.Duration(backoff) * 300 * time.Millisecond)
		// 口令正确仅动态码错 → 用 BAD_CODE 让前端聚焦动态码框
		code := "BAD_PASSWORD"
		if pwOK && !codeOK {
			code = "BAD_CODE"
		}
		c.JSON(http.StatusUnauthorized, gin.H{"error": gin.H{"code": code, "remaining": a.lockAfter - fails}})
		return
	}

	a.mu.Lock()
	a.fails = 0
	a.mu.Unlock()

	// Secure 仅在 HTTPS 下设置（本地 http 时关闭，否则 cookie 不生效）
	a.setCookie(c)
	c.JSON(http.StatusOK, gin.H{"data": "ok"})
}

func (a *Auth) Logout(c *gin.Context) {
	c.SetCookie(CookieName, "", -1, "/", "", false, true)
	c.JSON(http.StatusOK, gin.H{"data": "ok"})
}

// NeedsSetup 是否尚未设置登录口令（首次使用）。前端据此进入「首次设置口令」流程。
func (a *Auth) NeedsSetup() bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.password == ""
}

// PubConfig 公开端点：登录页据此决定是否显示动态码输入框、以及是否需要首次设置口令
// （仅暴露开关，不泄露密钥/口令）。
func (a *Auth) PubConfig(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"data": gin.H{
		"totp":       a.TOTPEnabled(),
		"needsSetup": a.NeedsSetup(),
	}})
}

// Setup 公开端点：仅当尚未设置口令时可用。设置初始口令并落盘，成功后直接发会话 Cookie
// （满足「界面上直接进，但必须先配置口令」）。
func (a *Auth) Setup(c *gin.Context) {
	if !a.NeedsSetup() {
		c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "ALREADY_SET", "message": "口令已设置"}})
		return
	}
	var body struct {
		Password string `json:"password"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	pw := strings.TrimSpace(body.Password)
	if len(pw) < 6 {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "WEAK_PASSWORD", "message": "口令至少 6 位"}})
		return
	}
	if err := a.persistPassword(pw); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "SAVE_FAILED", "message": "写入配置失败"}})
		return
	}
	a.setCookie(c)
	c.JSON(http.StatusOK, gin.H{"data": "ok"})
}

// ChangePassword 受保护端点：校验旧口令后改为新口令并落盘。
func (a *Auth) ChangePassword(c *gin.Context) {
	var body struct {
		Old string `json:"old"`
		New string `json:"new"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	a.mu.Lock()
	cur := a.password
	a.mu.Unlock()
	if cur == "" || subtle.ConstantTimeCompare([]byte(body.Old), []byte(cur)) != 1 {
		c.JSON(http.StatusUnauthorized, gin.H{"error": gin.H{"code": "BAD_PASSWORD", "message": "原口令不正确"}})
		return
	}
	pw := strings.TrimSpace(body.New)
	if len(pw) < 6 {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "WEAK_PASSWORD", "message": "口令至少 6 位"}})
		return
	}
	if err := a.persistPassword(pw); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "SAVE_FAILED", "message": "写入配置失败"}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": "ok"})
}

// persistPassword 更新内存口令并落盘（若配置了 savePW）。落盘失败则回滚内存值。
func (a *Auth) persistPassword(pw string) error {
	a.mu.Lock()
	prev := a.password
	a.password = pw
	a.mu.Unlock()
	if a.savePW == nil {
		return nil
	}
	if err := a.savePW(pw); err != nil {
		a.mu.Lock()
		a.password = prev
		a.mu.Unlock()
		return err
	}
	return nil
}

// setCookie 发一枚已登录会话 Cookie（与 Login 成功分支一致）。
func (a *Auth) setCookie(c *gin.Context) {
	secure := c.Request.TLS != nil || strings.HasPrefix(strings.ToLower(c.GetHeader("X-Forwarded-Proto")), "https")
	c.SetSameSite(http.SameSiteStrictMode)
	c.SetCookie(CookieName, a.issue(), int(a.ttl.Seconds()), "/", "", secure, true)
}

// requireReauthentication checks a fresh credential even for an authenticated session.
func (a *Auth) requireReauthentication(c *gin.Context) bool {
	var body struct {
		Password string `json:"password"`
		Code     string `json:"code"`
	}
	if c.ShouldBindJSON(&body) != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return false
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if time.Now().Before(a.lockedUntil) {
		c.JSON(http.StatusTooManyRequests, gin.H{"error": gin.H{"code": "LOCKED"}})
		return false
	}
	pwOK := a.password != "" && subtle.ConstantTimeCompare([]byte(body.Password), []byte(a.password)) == 1
	codeOK := a.totpOn && a.totpSecret != "" && verifyTOTP(a.totpSecret, body.Code)
	if !pwOK && !codeOK {
		a.fails++
		if a.fails >= a.lockAfter {
			a.lockedUntil = time.Now().Add(time.Duration(a.lockSecs) * time.Second)
			a.fails = 0
		}
		c.JSON(http.StatusForbidden, gin.H{"error": gin.H{"code": "REAUTH_REQUIRED"}})
		return false
	}
	a.fails = 0
	return true
}

// TOTPQR 受保护端点：返回当前状态与已配置密钥的 otpauth 链接（供再次扫码加设备）。
func (a *Auth) TOTPQR(c *gin.Context) {
	if !a.requireReauthentication(c) {
		return
	}
	a.mu.Lock()
	on, s := a.totpOn && a.totpSecret != "", a.totpSecret
	a.mu.Unlock()
	if !on {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"enabled": false}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{
		"enabled": true,
		"secret":  s,
		"uri":     OtpauthURI(s, "ttmux", "admin"),
	}})
}

// TOTPGen 受保护端点：生成一个新随机密钥（不持久化），返回二维码链接，供「开启」时扫码确认。
func (a *Auth) TOTPGen(c *gin.Context) {
	s := GenerateSecret()
	c.JSON(http.StatusOK, gin.H{"data": gin.H{
		"secret": s,
		"uri":    OtpauthURI(s, "ttmux", "admin"),
		"env":    "TTMUX_WEB_TOTP_SECRET=" + s,
	}})
}

// TOTPEnable 受保护端点：用密钥 + 一个有效动态码确认后，启用两步验证并持久化（无需重启）。
func (a *Auth) TOTPEnable(c *gin.Context) {
	if a.TOTPEnabled() {
		c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "TOTP_ALREADY_ENABLED"}})
		return
	}
	var b struct {
		Secret string `json:"secret"`
		Code   string `json:"code"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	s := strings.ToUpper(strings.TrimSpace(b.Secret))
	if s == "" || !verifyTOTP(s, strings.TrimSpace(b.Code)) {
		c.JSON(http.StatusUnauthorized, gin.H{"error": gin.H{"code": "BAD_CODE", "message": "动态码不正确，请用最新的码再试"}})
		return
	}
	a.mu.Lock()
	a.totpSecret, a.totpOn = s, true
	a.mu.Unlock()
	a.saveState()
	c.JSON(http.StatusOK, gin.H{"data": "ok"})
}

// TOTPDisable 受保护端点：关闭两步验证并持久化。
func (a *Auth) TOTPDisable(c *gin.Context) {
	if !a.requireReauthentication(c) {
		return
	}
	a.mu.Lock()
	a.totpOn = false
	a.mu.Unlock()
	a.saveState()
	c.JSON(http.StatusOK, gin.H{"data": "ok"})
}
