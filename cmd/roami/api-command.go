package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/ybz21/Roami/backend/config"
	"golang.org/x/term"
)

type apiConnection struct {
	client      *http.Client
	origin      string
	credentials string
}
type savedCookie struct {
	Origin  string         `json:"origin"`
	Cookies []*http.Cookie `json:"cookies"`
}

func connectAPI(server string) (*apiConnection, error) {
	if server == "" {
		server = os.Getenv("ROAMI_SERVER")
	}
	if server == "" {
		// Reading CLI connection settings must not create or rewrite config.yaml.
		content, err := os.ReadFile(config.ResolvePath())
		if err != nil {
			return nil, fmt.Errorf("读取服务配置: %w", err)
		}
		conf, err := config.Parse(content, config.ResolvePath())
		if err != nil {
			return nil, err
		}
		host := conf.Web.Bind
		host = strings.Replace(host, "0.0.0.0", "127.0.0.1", 1)
		if strings.HasPrefix(host, ":") {
			host = "127.0.0.1" + host
		}
		if host == "" {
			host = "127.0.0.1:13579"
		}
		scheme := "http"
		if conf.Web.TLS {
			scheme = "https"
		}
		server = scheme + "://" + host
	}
	u, err := url.Parse(server)
	if err != nil || u.Host == "" || u.User != nil || (u.Scheme != "https" && u.Scheme != "http") || (u.Path != "" && u.Path != "/") || u.RawQuery != "" || u.Fragment != "" {
		return nil, fmt.Errorf("无效服务地址")
	}
	u.Path = ""
	origin := strings.TrimRight(u.String(), "/")
	jar, _ := cookiejar.New(nil)
	transport := http.DefaultTransport.(*http.Transport).Clone()
	roots, _ := x509.SystemCertPool()
	if roots == nil {
		roots = x509.NewCertPool()
	}
	if ca, e := os.ReadFile(filepath.Join(dataDir(), "tls", "ca-cert.pem")); e == nil {
		roots.AppendCertsFromPEM(ca)
	}
	transport.TLSClientConfig = &tls.Config{RootCAs: roots, MinVersion: tls.VersionTLS12}
	client := &http.Client{Timeout: 30 * time.Second, Jar: jar, Transport: transport, CheckRedirect: func(req *http.Request, via []*http.Request) error { return http.ErrUseLastResponse }}
	path := filepath.Join(config.Home(), "credentials", url.QueryEscape(origin)+".json")
	var saved savedCookie
	if b, e := os.ReadFile(path); e == nil {
		if json.Unmarshal(b, &saved) == nil && saved.Origin == origin {
			jar.SetCookies(u, saved.Cookies)
		}
	}
	return &apiConnection{client: client, origin: origin, credentials: path}, nil
}

func (a *apiConnection) request(method, path string, body any) (json.RawMessage, error) {
	var input io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		input = bytes.NewReader(b)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, method, a.origin+path, input)
	if err != nil {
		return nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	res, err := a.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("连接失败（先运行 roami server）: %w", err)
	}
	defer res.Body.Close()
	b, err := io.ReadAll(io.LimitReader(res.Body, 8<<20))
	if err != nil {
		return nil, err
	}
	if !json.Valid(b) {
		return nil, fmt.Errorf("服务返回非 JSON 响应（HTTP %d）", res.StatusCode)
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return nil, &apiFailure{raw: b, status: res.StatusCode}
	}
	return b, nil
}

type apiFailure struct {
	raw    []byte
	status int
}

func (e *apiFailure) Error() string { return fmt.Sprintf("HTTP %d: %s", e.status, e.raw) }

func runAPICommand(group string, args []string) int {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" {
		fmt.Printf("roami %s ", group)
		if group == "auth" {
			fmt.Println("login|logout|status [--server URL] [--stdin] [--json]")
		} else {
			fmt.Println("ls|show|sessions|create|prefs|activity|remove [--server URL] [--json]")
		}
		return 0
	}
	sub := args[0]
	fs := flag.NewFlagSet(group+" "+sub, flag.ContinueOnError)
	server := fs.String("server", "", "Roami 服务地址")
	asJSON := fs.Bool("json", false, "JSON 输出")
	stdin := fs.Bool("stdin", false, "从 stdin 读取登录 JSON")
	provisionKey := fs.String("provision-key", "", "idempotent exclusive new-project key")
	baseDir := fs.String("base-dir", "", "parent directory for a provisioned project")
	name := fs.String("name", "", "显示名")
	clone := fs.String("clone", "", "克隆地址")
	pinned := fs.String("pinned", "", "true/false")
	agent := fs.String("agent", "", "默认 agent")
	base := fs.String("base", "", "默认基准")
	// Flags may follow the positional ID/path, as in the public examples.
	var positionals, options []string
	for i := 1; i < len(args); i++ {
		if strings.HasPrefix(args[i], "-") {
			options = append(options, args[i])
			if !strings.Contains(args[i], "=") && args[i] != "--json" && args[i] != "--stdin" && i+1 < len(args) {
				i++
				options = append(options, args[i])
			}
		} else {
			positionals = append(positionals, args[i])
		}
	}
	if err := fs.Parse(options); err != nil {
		return 2
	}
	fail := func(err error) int {
		var af *apiFailure
		if *asJSON {
			if errors.As(err, &af) {
				fmt.Println(string(af.raw))
			} else {
				b, _ := json.Marshal(map[string]any{"error": map[string]string{"code": "CLI_ERROR", "message": err.Error()}})
				fmt.Println(string(b))
			}
		} else {
			fmt.Fprintln(os.Stderr, err)
		}
		return 1
	}
	a, err := connectAPI(*server)
	if err != nil {
		return fail(err)
	}
	if group == "auth" {
		switch sub {
		case "login":
			var body struct {
				Password string `json:"password"`
				Code     string `json:"code"`
			}
			if *stdin {
				if err := json.NewDecoder(io.LimitReader(os.Stdin, 65536)).Decode(&body); err != nil {
					return fail(err)
				}
			} else {
				if !term.IsTerminal(int(os.Stdin.Fd())) {
					return fail(fmt.Errorf("非交互登录请使用 --stdin 输入 password/code JSON"))
				}
				fmt.Fprint(os.Stderr, "Password: ")
				b, e := term.ReadPassword(int(os.Stdin.Fd()))
				fmt.Fprintln(os.Stderr)
				if e != nil {
					return fail(e)
				}
				body.Password = string(b)
				fmt.Fprint(os.Stderr, "TOTP（未启用时留空）: ")
				body.Code, _ = bufio.NewReader(os.Stdin).ReadString('\n')
				body.Code = strings.TrimSpace(body.Code)
			}
			raw, e := a.request("POST", "/api/login", body)
			if e != nil {
				return fail(e)
			}
			u, _ := url.Parse(a.origin)
			b, _ := json.Marshal(savedCookie{Origin: a.origin, Cookies: a.client.Jar.Cookies(u)})
			if e = os.MkdirAll(filepath.Dir(a.credentials), 0700); e != nil {
				return fail(e)
			}
			f, e := os.CreateTemp(filepath.Dir(a.credentials), "cookie-*")
			if e != nil {
				return fail(e)
			}
			defer os.Remove(f.Name())
			if _, e = f.Write(b); e != nil {
				f.Close()
				return fail(e)
			}
			if e = f.Close(); e != nil {
				return fail(e)
			}
			if e = os.Rename(f.Name(), a.credentials); e != nil {
				return fail(e)
			}
			fmt.Println(string(raw))
			return 0
		case "logout":
			raw, e := a.request("POST", "/api/logout", nil)
			_ = os.Remove(a.credentials)
			if e != nil {
				return fail(e)
			}
			fmt.Println(string(raw))
			return 0
		case "status":
			raw, e := a.request("GET", "/api/me", nil)
			if e != nil {
				return fail(e)
			}
			fmt.Println(string(raw))
			return 0
		default:
			return fail(fmt.Errorf("未知 auth 命令 %q", sub))
		}
	}
	target := ""
	if len(positionals) > 0 {
		target = positionals[0]
	}
	var raw json.RawMessage
	switch sub {
	case "ls":
		raw, err = a.request("GET", "/api/projects", nil)
	case "sessions":
		if target == "" {
			return fail(fmt.Errorf("需要 project ID"))
		}
		raw, err = a.request("GET", "/api/projects?sessionProject="+url.QueryEscape(target), nil)
	case "show":
		if target == "" {
			return fail(fmt.Errorf("需要 project ID"))
		}
		raw, err = a.request("GET", "/api/projects", nil)
		if err == nil {
			var envelope struct {
				Data struct {
					Projects []json.RawMessage `json:"projects"`
				} `json:"data"`
			}
			if err = json.Unmarshal(raw, &envelope); err == nil {
				var found json.RawMessage
				for _, item := range envelope.Data.Projects {
					var v struct {
						Key string `json:"key"`
					}
					_ = json.Unmarshal(item, &v)
					if v.Key == target {
						found = item
						break
					}
				}
				if found == nil {
					err = fmt.Errorf("UNKNOWN_PROJECT: %s", target)
				} else {
					raw, _ = json.Marshal(map[string]any{"data": found})
				}
			}
		}
	case "create":
		if target == "" && *provisionKey == "" {
			return fail(fmt.Errorf("需要目录"))
		}
		if strings.HasPrefix(target, "~/") {
			home, _ := os.UserHomeDir()
			target = filepath.Join(home, target[2:])
		}
		if target != "" {
			target, err = filepath.Abs(target)
		}
		if err == nil {
			raw, err = a.request("POST", "/api/projects", map[string]string{"dir": target, "displayName": *name, "cloneUrl": *clone, "provisionKey": *provisionKey, "baseDir": *baseDir})
		}
	case "remove", "activity", "prefs":
		if target == "" {
			return fail(fmt.Errorf("需要 project ID"))
		}
		path := "/api/projects/" + url.PathEscape(target)
		switch sub {
		case "remove":
			raw, err = a.request("DELETE", path, nil)
		case "activity":
			raw, err = a.request("GET", path+"/activity", nil)
		case "prefs":
			patch := map[string]any{}
			fs.Visit(func(f *flag.Flag) {
				switch f.Name {
				case "name":
					patch["displayName"] = *name
				case "agent":
					patch["defaultAgent"] = *agent
				case "base":
					patch["defaultBase"] = *base
				case "pinned":
					if *pinned == "true" {
						patch["pinned"] = true
					} else if *pinned == "false" {
						patch["pinned"] = false
					} else {
						err = fmt.Errorf("--pinned 必须为 true 或 false")
					}
				}
			})
			if err == nil {
				raw, err = a.request("PATCH", path+"/prefs", patch)
			}
		}
	default:
		return fail(fmt.Errorf("未知 project 命令 %q", sub))
	}
	if err != nil {
		return fail(err)
	}
	if *asJSON {
		fmt.Println(string(raw))
	} else {
		var out bytes.Buffer
		if json.Indent(&out, raw, "", "  ") == nil {
			fmt.Println(out.String())
		} else {
			fmt.Println(string(raw))
		}
	}
	return 0
}
