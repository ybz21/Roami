// Package config 负责 Roami 后端的配置：从 ~/.roami/config.yaml 读取（首次缺失则由
// 内嵌模板生成），并按「命令行 flag > 环境变量 > 配置文件 > 默认值」的优先级解析。
//
// flag 覆盖在 backend/cmd 里叠加（flag 定义在 main）；本包负责 env + 文件 + 默认值，
// 以及登录口令的落盘（SavePassword，供首次设置/改密使用，明文写回，保留注释）。
package config

import (
	_ "embed"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"
)

//go:embed config.yaml.template
var templateBytes []byte

// Web 对应 config.yaml 里的 web: 段。
type Web struct {
	Password   string   `yaml:"password"`
	Bind       string   `yaml:"bind"`
	TLS        bool     `yaml:"tls"`
	TLSSAN     []string `yaml:"tls_san"`
	TOTPSecret string   `yaml:"totp_secret"`
	TwoFA      string   `yaml:"two_fa"`
	LockAfter  int      `yaml:"lock_after"`
	LockSecs   int      `yaml:"lock_secs"`

	// P2P 直连（浏览器 ↔ pion 经 WebRTC DataChannel）。M0a spike：STUN-only。
	// P2PEnabled 为灰度总开关；P2PICEServers 为 STUN/TURN 服务列表。
	P2PEnabled    bool     `yaml:"p2p_enabled"`
	P2PICEServers []string `yaml:"p2p_ice_servers"`

	// M0b 跨网穿透杠杆（默认关时行为与 M0a 逐字节一致）：
	// P2PUDPPort>0 → 固定 UDP 端口 + UDPMux（便于手动端口转发/UPnP 端口一致）；0=随机。
	// P2PUPnP → 仅当 P2PUDPPort>0 时尝试 UPnP 端口映射，external==internal 才注入 srflx。
	// P2PMDNS → pion 解析浏览器 .local mDNS 候选；默认 true（对 localhost/LAN 无害有益）。
	P2PUDPPort int  `yaml:"p2p_udp_port"`
	P2PUPnP    bool `yaml:"p2p_upnp"`
	P2PMDNS    bool `yaml:"p2p_mdns"`
}

// DefaultICEServers 是 p2p_ice_servers 留空时的默认 STUN 列表。
//
// 多写几台不是冗余：这些地址是并行查询的，谁先回谁先给出 srflx 候选，一台不可达也只是
// 少一条候选、不阻塞其余（实测见 docs/design/p2p/stun-servers.md）。国内两台排在前面纯粹
// 因为快——本机实测 3~10ms，Google 那几台 100~180ms，而我们等的就是第一个 srflx。
//
// 都是公共服务，只做 NAT 映射发现、不承载数据；要自建就在配置里覆盖整份列表。
var DefaultICEServers = []string{
	"stun:stun.miwifi.com:3478",
	"stun:stun.chat.bilibili.com:3478",
	"stun:stun.l.google.com:19302",
	"stun:stun1.l.google.com:19302",
	"stun:global.stun.twilio.com:3478",
}

// Cluster 对应 config.yaml 里的 cluster: 段（横向扩展：标准节点 / 中心）。
// mode=standard（默认）为现在的单机 Roami，填了 broker 就额外出站注册进云端；
// mode=cloud 是中心，只做路由 + 注册表 + 控制台，不跑业务。
// 见 docs/design/cluster/architecture.html。
type Cluster struct {
	Mode     string `yaml:"mode"`     // standard（默认）| hub。旧值 cloud 仍能读
	Hub      string `yaml:"hub"`      // 中心地址（standard 模式填了才上云）。旧键 broker: 仍能读，见 Load
	Token    string `yaml:"token"`    // 一次性 enrollment token（首次注册用，之后换长期节点凭证）
	Name     string `yaml:"name"`     // 节点显示名（默认 hostname）
	Group    string `yaml:"group"`    // 分组（可选）
	Insecure bool   `yaml:"insecure"` // 跳过中心 TLS 校验（自签证书调试用，生产勿开）

	// 以下两项只对 mode=hub 有意义。
	//
	// PublicURL 是**机器要拨过来用的那个地址**。中心不知道自己在外面叫什么——它看到的是
	// 网卡上的内网地址（云主机上常是 172.17.x），而接入命令里必须写外面能到的那个。
	// 留空则回落到「当前这次请求的 Host」，那只在「你用什么地址管它、机器就用什么地址接」
	// 时才成立；反代/frp/内外网双地址的场景必须显式填。
	PublicURL string `yaml:"public_url"`
	// EnrollTTLMin 接入令牌有效期（分钟）。默认 30；跨时区手动粘贴命令时可以调长。
	EnrollTTLMin int `yaml:"enroll_ttl_min"`
}

// Config 是解析后的配置（env 覆盖已叠加，默认值已填充）。
type Config struct {
	Web     Web
	Cluster Cluster
	Path    string // 实际配置文件路径（供 SavePassword 落盘）
}

// Home 返回 Roami 主目录（数据/配置根）。优先 ROAMI_HOME，兼容旧 ROAM_HOME / TTMUX_HOME。
func Home() string {
	if d := firstEnv("ROAMI_HOME", "ROAM_HOME", "TTMUX_HOME"); d != "" {
		return d
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".roami")
}

// ResolvePath 解析配置文件路径：ROAMI_CONFIG（兼容 ROAM_CONFIG）> <home>/config.yaml。
func ResolvePath() string {
	if p := firstEnv("ROAMI_CONFIG", "ROAM_CONFIG"); p != "" {
		return p
	}
	return filepath.Join(Home(), "config.yaml")
}

// Load 读取并解析配置。若文件缺失，先用内嵌模板生成再读。
// 解析顺序：文件 → 默认值兜底 → 环境变量覆盖。flag 覆盖由调用方(main)叠加。
func Load(path string) (*Config, error) {
	if path == "" {
		path = ResolvePath()
	}
	if _, err := os.Stat(path); os.IsNotExist(err) {
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			return nil, err
		}
		if err := os.WriteFile(path, templateBytes, 0o600); err != nil {
			return nil, err
		}
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return Parse(b, path)
}

// Parse reads existing configuration without creating files.
func Parse(b []byte, path string) (*Config, error) {
	var file struct {
		Web     Web     `yaml:"web"`
		Cluster Cluster `yaml:"cluster"`
	}
	// 旧键兼容：这套东西一度叫 broker / cloud。用户口径统一成「中心 / hub」之后，
	// 配置也跟着改名——但已经写进 config.yaml 的那些不能一改就断，所以旧键仍然读，
	// 只是不再往外写（SaveCluster 只写新键）。
	var legacy struct {
		Cluster struct {
			Broker string `yaml:"broker"`
		} `yaml:"cluster"`
	}
	_ = yaml.Unmarshal(b, &legacy)
	if err := yaml.Unmarshal(b, &file); err != nil {
		return nil, err
	}
	// p2p_mdns 缺省为 true：用 *bool 探测「文件里是否显式写了该键」，
	// 未写则默认开（对 localhost/LAN 无害且有益），显式 false 才关。
	var mdnsProbe struct {
		Web struct {
			P2PMDNS *bool `yaml:"p2p_mdns"`
		} `yaml:"web"`
	}
	_ = yaml.Unmarshal(b, &mdnsProbe)
	if mdnsProbe.Web.P2PMDNS == nil {
		file.Web.P2PMDNS = true
	}
	if file.Cluster.Hub == "" {
		file.Cluster.Hub = legacy.Cluster.Broker
	}
	c := &Config{Web: file.Web, Cluster: file.Cluster, Path: path}
	c.applyDefaults()
	c.applyEnv()
	return c, nil
}

func (c *Config) applyDefaults() {
	if c.Web.Bind == "" {
		c.Web.Bind = "0.0.0.0:13579"
	}
	if c.Web.LockAfter <= 0 {
		c.Web.LockAfter = 10
	}
	if c.Web.LockSecs <= 0 {
		c.Web.LockSecs = 30
	}
	c.Web.P2PICEServers = normalizeICEServers(c.Web.P2PICEServers)
	if len(c.Web.P2PICEServers) == 0 {
		c.Web.P2PICEServers = append([]string(nil), DefaultICEServers...)
	}
	if c.Cluster.Mode == "" {
		c.Cluster.Mode = "standard"
	}
	if c.Cluster.EnrollTTLMin <= 0 {
		c.Cluster.EnrollTTLMin = 30
	}
	if c.Cluster.Mode == "cloud" {
		c.Cluster.Mode = "hub" // 旧值：这个模式一度叫 cloud，但中心完全可以是家里的一台小主机
	}
}

// applyEnv 让环境变量覆盖文件值。主键为 ROAM_*，兼容旧 TTMUX_*。
func (c *Config) applyEnv() {
	if v := firstEnv("ROAM_WEB_PASSWORD", "TTMUX_WEB_PASSWORD"); v != "" {
		c.Web.Password = v
	}
	if v := firstEnv("ROAM_WEB_BIND", "TTMUX_WEB_BIND"); v != "" {
		c.Web.Bind = v
	}
	if v := firstEnv("ROAM_WEB_TLS", "TTMUX_WEB_TLS"); v != "" {
		c.Web.TLS = truthy(v)
	}
	if v := firstEnv("ROAM_WEB_TLS_SAN", "TTMUX_WEB_TLS_SAN"); v != "" {
		c.Web.TLSSAN = splitCSV(v)
	}
	if v := firstEnv("ROAM_WEB_TOTP_SECRET", "TTMUX_WEB_TOTP_SECRET"); v != "" {
		c.Web.TOTPSecret = v
	}
	if v := firstEnv("ROAM_WEB_2FA", "TTMUX_WEB_2FA"); v != "" {
		c.Web.TwoFA = v
	}
	if v := firstEnv("ROAM_WEB_LOCK_AFTER", "TTMUX_WEB_LOCK_AFTER"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			c.Web.LockAfter = n
		}
	}
	if v := firstEnv("ROAM_WEB_LOCK_SECS", "TTMUX_WEB_LOCK_SECS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			c.Web.LockSecs = n
		}
	}
	if v := firstEnv("ROAM_WEB_P2P_ENABLE", "TTMUX_WEB_P2P_ENABLE"); v != "" {
		c.Web.P2PEnabled = truthy(v)
	}
	if v := firstEnv("ROAM_WEB_P2P_ICE_SERVERS", "TTMUX_WEB_P2P_ICE_SERVERS"); v != "" {
		c.Web.P2PICEServers = normalizeICEServers(splitCSV(v))
	}
	if v := firstEnv("ROAM_WEB_P2P_UDP_PORT", "TTMUX_WEB_P2P_UDP_PORT"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			c.Web.P2PUDPPort = n
		}
	}
	if v := firstEnv("ROAM_WEB_P2P_UPNP", "TTMUX_WEB_P2P_UPNP"); v != "" {
		c.Web.P2PUPnP = truthy(v)
	}
	if v := firstEnv("ROAM_WEB_P2P_MDNS", "TTMUX_WEB_P2P_MDNS"); v != "" {
		c.Web.P2PMDNS = truthy(v)
	}
	// cluster 段的环境变量覆盖（横向扩展）。
	if v := firstEnv("ROAM_CLUSTER_MODE"); v != "" {
		c.Cluster.Mode = v
	}
	if v := firstEnv("ROAM_CLUSTER_HUB", "ROAM_CLUSTER_BROKER"); v != "" {
		c.Cluster.Hub = v
	}
	if v := firstEnv("ROAM_CLUSTER_TOKEN"); v != "" {
		c.Cluster.Token = v
	}
	if v := firstEnv("ROAM_CLUSTER_NAME"); v != "" {
		c.Cluster.Name = v
	}
	if v := firstEnv("ROAM_CLUSTER_GROUP"); v != "" {
		c.Cluster.Group = v
	}
	if v := firstEnv("ROAM_CLUSTER_INSECURE"); v != "" {
		c.Cluster.Insecure = truthy(v)
	}
	if v := firstEnv("ROAM_CLUSTER_PUBLIC_URL"); v != "" {
		c.Cluster.PublicURL = v
	}
}

// ResolvedTOTPSecret 返回生效的两步验证初始种子：two_fa 为 off/0/false/no 时置空。
func (c *Config) ResolvedTOTPSecret() string {
	switch strings.ToLower(strings.TrimSpace(c.Web.TwoFA)) {
	case "off", "0", "false", "no":
		return ""
	}
	return c.Web.TOTPSecret
}

var passwordLineRE = regexp.MustCompile(`(?m)^(\s*password:\s*).*$`)

// SavePassword 把登录口令明文写回 config.yaml，只改 password: 那一行，保留其余注释/字段。
// 用于首次设置口令与设置页改密。
func SavePassword(path, plaintext string) error {
	if path == "" {
		path = ResolvePath()
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	quoted := yamlQuote(plaintext)
	var out []byte
	if passwordLineRE.Match(b) {
		out = passwordLineRE.ReplaceAll(b, []byte("${1}"+quoted))
	} else {
		// 兜底：没有 password 行时追加到 web: 段（极少发生，模板总带该行）。
		out = append(b, []byte("\nweb:\n  password: "+quoted+"\n")...)
	}
	return os.WriteFile(path, out, 0o600)
}

// yamlQuote 生成 YAML 双引号字符串字面量（转义反斜杠与双引号）。
func yamlQuote(s string) string {
	s = strings.ReplaceAll(s, `\`, `\\`)
	s = strings.ReplaceAll(s, `"`, `\"`)
	return `"` + s + `"`
}

func firstEnv(keys ...string) string {
	for _, k := range keys {
		if v := os.Getenv(k); v != "" {
			return v
		}
	}
	return ""
}

func truthy(s string) bool {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "", "0", "off", "false", "no":
		return false
	}
	return true
}

// normalizeICEServers 清理 ICE server 列表：去空白、补 stun: 前缀、按原序去重。
//
// 补前缀是因为「stun.miwifi.com:3478」这样漏掉 scheme 的写法太自然了，而 pion 与浏览器
// 都会把它整条丢掉——一台配了却从不生效的 STUN 比没配更难查。
func normalizeICEServers(in []string) []string {
	out := make([]string, 0, len(in))
	seen := map[string]bool{}
	for _, u := range in {
		u = strings.TrimSpace(u)
		if u == "" {
			continue
		}
		if !strings.Contains(u, ":") {
			continue // 连主机:端口都不是，不猜
		}
		if !strings.HasPrefix(u, "stun:") && !strings.HasPrefix(u, "stuns:") &&
			!strings.HasPrefix(u, "turn:") && !strings.HasPrefix(u, "turns:") {
			u = "stun:" + u
		}
		if !seen[u] {
			seen[u] = true
			out = append(out, u)
		}
	}
	return out
}

func splitCSV(s string) []string {
	parts := strings.Split(s, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}
