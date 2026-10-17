package server

import (
	"net"
	"net/http"
	"os"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/cluster/node"
	"github.com/ybz21/Roami/backend/config"
)

// 设置页的「多机」那一块：读当前角色与接入状态、写回 config.yaml。
//
// 只有两种角色，接口也照这个口径给（见 docs/design/cluster/settings.html）：
//
//	mode=standard —— 这台机器：跑活，可选接到一个中心上
//	mode=cloud    —— 中心：只当入口，不跑活
//
// **接入用的是一次性令牌，不是中心的登录口令。** 口令是给人登录浏览器用的，
// 机器接入走令牌换长期凭证——这条要在接口和界面上都说清，否则用户第一反应是去填密码。
type clusterAPI struct {
	cfgPath string
	cluster config.Cluster
	client  *node.Client // standard 且配了 broker 时才有
	bind    string
	tls     bool
}

type clusterView struct {
	Mode     string `json:"mode"`
	Hub      string `json:"hub"`
	Name     string `json:"name"`
	Group    string `json:"group"`
	Insecure bool   `json:"insecure"`
	// 令牌只写不读：读回来对界面没用，还多一个泄漏面。只告诉前端「配过没有」。
	HasToken bool `json:"hasToken"`
	// 接入状态；未配置中心时为空。
	State *node.State `json:"state,omitempty"`
	// 这台机器的局域网直连地址——用户配完第一个想确认的就是「那我输哪个网址」。
	LANURLs []string `json:"lanUrls"`

	// 只有 mode=hub 用得上：对外地址与令牌有效期。
	PublicURL    string `json:"publicUrl"`
	EnrollTTLMin int    `json:"enrollTtlMin"`
}

func (a *clusterAPI) Get(c *gin.Context) {
	v := clusterView{
		Mode: a.cluster.Mode, Hub: a.cluster.Hub, Name: a.cluster.Name,
		Group: a.cluster.Group, Insecure: a.cluster.Insecure,
		HasToken: a.cluster.Token != "", LANURLs: lanURLs(a.bind, a.tls),
		PublicURL: a.cluster.PublicURL, EnrollTTLMin: a.cluster.EnrollTTLMin,
	}
	if v.Mode == "" {
		v.Mode = "standard"
	}
	if a.client != nil {
		st := a.client.Status()
		v.State = &st
	}
	c.JSON(http.StatusOK, gin.H{"data": v})
}

func (a *clusterAPI) Put(c *gin.Context) {
	var body struct {
		Mode         string  `json:"mode"`
		Hub          string  `json:"hub"`
		Token        *string `json:"token"` // 指针：不传 = 保留原令牌，传空串 = 清掉
		Name         string  `json:"name"`
		Group        string  `json:"group"`
		Insecure     bool    `json:"insecure"`
		PublicURL    *string `json:"publicUrl"`
		EnrollTTLMin *int    `json:"enrollTtlMin"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	if body.Mode != "standard" && body.Mode != "hub" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_MODE"}})
		return
	}
	next := config.Cluster{
		Mode: body.Mode, Hub: strings.TrimSpace(body.Hub),
		Name: body.Name, Group: body.Group, Insecure: body.Insecure,
		Token:        a.cluster.Token,
		PublicURL:    a.cluster.PublicURL,
		EnrollTTLMin: a.cluster.EnrollTTLMin,
	}
	if body.PublicURL != nil {
		next.PublicURL = strings.TrimRight(strings.TrimSpace(*body.PublicURL), "/")
	}
	if body.EnrollTTLMin != nil && *body.EnrollTTLMin > 0 {
		next.EnrollTTLMin = *body.EnrollTTLMin
	}
	if body.Token != nil {
		next.Token = strings.TrimSpace(*body.Token)
	}
	// 中心不接别人，留着地址只会让人以为它还连着谁
	if next.Mode == "hub" {
		next.Hub, next.Token = "", ""
	}
	if err := config.SaveCluster(a.cfgPath, next); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "SAVE_FAILED", "message": err.Error()}})
		return
	}
	a.cluster = next
	// 角色变了要重启：cloud 与 standard 的依赖图不同（中心根本不构造业务 runtime），
	// 不是能热切的东西。前端据此提示并等它回来。
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"saved": true, "needsRestart": true}})
}

// Restart 让进程退出，由 systemd / start.sh 的守护把它拉起来。没有守护的话
// 就真的停了——所以前端要先说清「重启后自动回来；如果没回来，手动启动一次」。
func (a *clusterAPI) Restart(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"restarting": true}})
	go func() {
		flushed := c.Writer
		if f, ok := flushed.(http.Flusher); ok {
			f.Flush()
		}
		os.Exit(0)
	}()
}

// lanURLs 列出这台机器在局域网里的访问地址。接入中心之后这条依然有效——
// 两条入口并存是设计要求，不是副作用。
func lanURLs(bind string, tls bool) []string {
	_, port, err := net.SplitHostPort(bind)
	if err != nil || port == "" {
		port = "13579"
	}
	scheme := "http"
	if tls {
		scheme = "https"
	}
	out := []string{}
	ifaces, _ := net.Interfaces()
	for _, ifi := range ifaces {
		if ifi.Flags&net.FlagUp == 0 || ifi.Flags&net.FlagLoopback != 0 || virtualIface(ifi.Name) {
			continue
		}
		addrs, _ := ifi.Addrs()
		for _, a := range addrs {
			ipnet, ok := a.(*net.IPNet)
			if !ok || ipnet.IP.IsLoopback() || ipnet.IP.To4() == nil {
				continue
			}
			out = append(out, scheme+"://"+ipnet.IP.String()+":"+port)
		}
	}
	return out
}

// virtualIface 挡掉容器/虚拟网桥。跑着 docker 的机器上 172.17.0.1 / 172.18.0.1 这类地址
// 会混进来，而它们对用户毫无意义——「我该输哪个网址」这个问题，给四个答案等于没给。
func virtualIface(name string) bool {
	for _, p := range []string{"docker", "br-", "veth", "virbr", "cni", "flannel", "kube", "tun", "tap", "zt", "wg", "tailscale"} {
		if strings.HasPrefix(name, p) {
			return true
		}
	}
	return false
}
