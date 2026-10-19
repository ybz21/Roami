package auth

import (
	"bytes"
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

func TestTOTPSensitiveActionsRequireFreshCredentials(t *testing.T) {
	gin.SetMode(gin.TestMode)
	secret := GenerateSecret()
	code, _ := totpAt(secret, uint64(time.Now().Unix()/30))
	for _, action := range []string{"qr", "disable"} {
		for _, credential := range []string{"", "wrong", "password", "totp"} {
			t.Run(action+"/"+credential, func(t *testing.T) {
				a := New("test-password", secret, "", 5, 30, nil)
				r := gin.New()
				r.POST("/qr", a.TOTPQR)
				r.POST("/disable", a.TOTPDisable)
				body := map[string]string{}
				if credential == "password" {
					body["password"] = "test-password"
				} else if credential == "totp" {
					body["code"] = code
				} else {
					body["password"] = credential
				}
				data, _ := json.Marshal(body)
				w := httptest.NewRecorder()
				req := httptest.NewRequest("POST", "/"+action, bytes.NewReader(data))
				req.Header.Set("Content-Type", "application/json")
				r.ServeHTTP(w, req)
				ok := credential == "password" || credential == "totp"
				if ok && w.Code != 200 {
					t.Fatalf("valid credential rejected: %d %s", w.Code, w.Body)
				}
				if !ok && (w.Code != 403 || strings.Contains(w.Body.String(), secret) || !a.TOTPEnabled()) {
					t.Fatalf("sensitive action accepted: %d %s", w.Code, w.Body)
				}
			})
		}
	}
}

func TestTOTPReauthenticationLocksRepeatedFailuresAndPreventsReplacement(t *testing.T) {
	a := New("test-password", GenerateSecret(), "", 2, 30, nil)
	r := gin.New()
	r.POST("/qr", a.TOTPQR)
	r.POST("/enable", a.TOTPEnable)
	for i, status := range []int{403, 403, 429} {
		w := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/qr", strings.NewReader(`{"password":"wrong"}`))
		req.Header.Set("Content-Type", "application/json")
		r.ServeHTTP(w, req)
		if w.Code != status {
			t.Fatalf("attempt %d: got %d want %d", i, w.Code, status)
		}
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest("POST", "/enable", strings.NewReader(`{}`)))
	if w.Code != 409 {
		t.Fatalf("enabled secret can be replaced: %d", w.Code)
	}
}
