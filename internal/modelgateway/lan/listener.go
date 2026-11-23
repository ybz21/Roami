// Package lan owns the gateway's LAN sockets and address discovery.
package lan

import (
	"errors"
	"net"
	"net/http"
	"slices"
	"strconv"
	"strings"
	"time"
)

var ErrUnavailable = errors.New("MODEL_GATEWAY_LAN_UNAVAILABLE")

func IsPrivatePeer(address string) bool {
	host, _, err := net.SplitHostPort(address)
	return err == nil && net.ParseIP(host).IsPrivate()
}

type Listener struct {
	server    *http.Server
	listeners []net.Listener
	urls      []string
}

func (lan *Listener) Close() {
	for _, listener := range lan.listeners {
		_ = listener.Close()
	}
	_ = lan.server.Close()
}

func PrivateIPv4Addresses() []string {
	addresses := []string{}
	interfaces, _ := net.Interfaces()
	for _, iface := range interfaces {
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		if slices.ContainsFunc([]string{"docker", "br-", "veth", "virbr", "cni", "flannel", "kube", "tun", "tap", "zt", "wg", "tailscale"}, func(prefix string) bool {
			return strings.HasPrefix(iface.Name, prefix)
		}) {
			continue
		}
		list, _ := iface.Addrs()
		for _, addr := range list {
			network, ok := addr.(*net.IPNet)
			if ok && network.IP.To4() != nil && network.IP.IsPrivate() {
				addresses = append(addresses, network.IP.String())
			}
		}
	}
	slices.Sort(addresses)
	return slices.Compact(addresses)
}

func Listen(port int, handler http.Handler) (*Listener, error) {
	lan := &Listener{
		server: &http.Server{Handler: handler, ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 60 * time.Second},
	}
	for _, address := range PrivateIPv4Addresses() {
		listener, err := net.Listen("tcp4", net.JoinHostPort(address, strconv.Itoa(port)))
		if err == nil {
			lan.listeners = append(lan.listeners, listener)
			lan.urls = append(lan.urls, "http://"+listener.Addr().String())
			go func() { _ = lan.server.Serve(listener) }()
		}
	}
	if len(lan.urls) == 0 {
		return nil, ErrUnavailable
	}
	return lan, nil
}

func (lan *Listener) URLs() []string { return slices.Clone(lan.urls) }
