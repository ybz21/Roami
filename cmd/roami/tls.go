// 自签 TLS：手机经局域网用麦克风/剪贴板等能力，浏览器要求「安全上下文」(HTTPS)。
// 这里在证书缺失时就地生成一张自签证书，SAN 覆盖 localhost、回环与本机所有非回环 IP，
// 让手机用 https://<局域网IP>:<端口> 访问（首次点「继续前往」信任即可）。
package main

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"net"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// ensureSelfSignedCert 在 cert/key 任一缺失时生成「根 CA + 叶子服务器证书」两张。
//   - ca-cert.pem（IsCA）：供手机/电脑安装为「受信任证书」。安卓走「CA 证书」安装路径，不要私钥。
//   - cert.pem（叶子, CA:FALSE, 由 CA 签发, 带 SAN）+ ca-cert.pem 合成链：服务器实际呈现给浏览器。
//
// 为什么分两张：浏览器(Chrome)不接受把一张 CA:TRUE 证书直接当服务器叶子证书；必须「装 CA → 信任其签发的叶子」。
// extraSAN 为额外证书 SAN（公网 IP 或域名，来自 config.yaml 的 web.tls_san / 环境变量）。
// 返回是否新生成。
func ensureSelfSignedCert(certPath, keyPath string, extraSAN []string) (bool, error) {
	if fileExists(certPath) && fileExists(keyPath) {
		return false, nil
	}
	dir := filepath.Dir(certPath)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return false, err
	}
	caCertPath := filepath.Join(dir, "ca-cert.pem")
	caKeyPath := filepath.Join(dir, "ca-key.pem")

	// ── 1) 根 CA（手机安装这张；只用于签发，不直接当服务器证书）──
	caPriv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return false, err
	}
	caSerial, err := randSerial()
	if err != nil {
		return false, err
	}
	caTmpl := x509.Certificate{
		SerialNumber:          caSerial,
		Subject:               pkix.Name{CommonName: "ttmux-web local CA"},
		NotBefore:             time.Now().Add(-1 * time.Hour),
		NotAfter:              time.Now().AddDate(10, 0, 0),
		KeyUsage:              x509.KeyUsageCertSign | x509.KeyUsageCRLSign | x509.KeyUsageDigitalSignature,
		BasicConstraintsValid: true,
		IsCA:                  true,
		MaxPathLenZero:        true, // 只签发叶子，不再签中间 CA
	}
	caDER, err := x509.CreateCertificate(rand.Reader, &caTmpl, &caTmpl, &caPriv.PublicKey, caPriv)
	if err != nil {
		return false, err
	}
	caCert, err := x509.ParseCertificate(caDER)
	if err != nil {
		return false, err
	}

	// ── 2) 叶子服务器证书（由 CA 签发，CA:FALSE，带 SAN）──
	leafPriv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return false, err
	}
	leafSerial, err := randSerial()
	if err != nil {
		return false, err
	}
	dns := []string{"localhost"}
	ips := append([]net.IP{net.IPv4(127, 0, 0, 1), net.IPv6loopback}, localIPs()...)
	// 额外 SAN：来自 config.yaml 的 web.tls_san（或环境变量）。经 frp/反代从公网 IP 或域名
	// 访问时填上，否则浏览器会因「证书域名不匹配」报错。是 IP 走 IPAddresses，否则当域名。
	for _, s := range extraSAN {
		if s = strings.TrimSpace(s); s == "" {
			continue
		}
		if ip := net.ParseIP(s); ip != nil {
			ips = append(ips, ip)
		} else {
			dns = append(dns, s)
		}
	}
	leafTmpl := x509.Certificate{
		SerialNumber:          leafSerial,
		Subject:               pkix.Name{CommonName: "ttmux-web"},
		NotBefore:             time.Now().Add(-1 * time.Hour),
		NotAfter:              time.Now().AddDate(10, 0, 0),
		KeyUsage:              x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
		ExtKeyUsage:           []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		BasicConstraintsValid: true,
		DNSNames:              dns,
		IPAddresses:           ips,
	}
	leafDER, err := x509.CreateCertificate(rand.Reader, &leafTmpl, caCert, &leafPriv.PublicKey, caPriv)
	if err != nil {
		return false, err
	}

	// CA 证书（手机下载安装用）+ CA 私钥（留存以便将来续签叶子）
	if err := writePEMCert(caCertPath, caDER); err != nil {
		return false, err
	}
	if err := writePEMKey(caKeyPath, caPriv); err != nil {
		return false, err
	}

	// 服务器证书链：叶子 + CA 一起写进 cert.pem，RunTLS 加载后向客户端呈现完整链
	certOut, err := os.OpenFile(certPath, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o644)
	if err != nil {
		return false, err
	}
	defer certOut.Close()
	if err := pem.Encode(certOut, &pem.Block{Type: "CERTIFICATE", Bytes: leafDER}); err != nil {
		return false, err
	}
	if err := pem.Encode(certOut, &pem.Block{Type: "CERTIFICATE", Bytes: caDER}); err != nil {
		return false, err
	}
	if err := writePEMKey(keyPath, leafPriv); err != nil {
		return false, err
	}
	return true, nil
}

func randSerial() (*big.Int, error) {
	return rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
}

func writePEMCert(path string, der []byte) error {
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	defer f.Close()
	return pem.Encode(f, &pem.Block{Type: "CERTIFICATE", Bytes: der})
}

func writePEMKey(path string, priv *ecdsa.PrivateKey) error {
	b, err := x509.MarshalECPrivateKey(priv)
	if err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o600)
	if err != nil {
		return err
	}
	defer f.Close()
	return pem.Encode(f, &pem.Block{Type: "EC PRIVATE KEY", Bytes: b})
}

func fileExists(p string) bool {
	st, err := os.Stat(p)
	return err == nil && !st.IsDir()
}

// localIPs 枚举本机所有非回环单播 IP，写进证书 SAN，减少手机访问时的「域名不匹配」告警。
func localIPs() []net.IP {
	var ips []net.IP
	addrs, err := net.InterfaceAddrs()
	if err != nil {
		return ips
	}
	for _, a := range addrs {
		var ip net.IP
		switch v := a.(type) {
		case *net.IPNet:
			ip = v.IP
		case *net.IPAddr:
			ip = v.IP
		}
		if ip == nil || ip.IsLoopback() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() {
			continue
		}
		ips = append(ips, ip)
	}
	return ips
}
