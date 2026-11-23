package modelgateway

import (
	"context"
	"errors"
	"net"
	"net/http"
	"slices"
	"strconv"
	"strings"
	"time"
)

type gatewayLANRequest struct{}

type gatewayLAN struct {
	server    *http.Server
	listeners []net.Listener
	urls      []string
}

func (lan *gatewayLAN) close() {
	for _, listener := range lan.listeners {
		_ = listener.Close()
	}
	_ = lan.server.Close()
}

func gatewayLANAddresses() []string {
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

func (h *Handler) serveGatewayLAN(w http.ResponseWriter, r *http.Request) {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil || !net.ParseIP(host).IsPrivate() {
		reject(w, http.StatusForbidden, "MODEL_GATEWAY_LAN_ONLY")
		return
	}
	h.publicModels(w, r.WithContext(context.WithValue(r.Context(), gatewayLANRequest{}, true)))
}

func (h *Handler) openGatewayLAN(port int) (*gatewayLAN, error) {
	lan := &gatewayLAN{
		server: &http.Server{Handler: http.HandlerFunc(h.serveGatewayLAN), ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 60 * time.Second},
	}
	for _, address := range gatewayLANAddresses() {
		listener, err := net.Listen("tcp4", net.JoinHostPort(address, strconv.Itoa(port)))
		if err == nil {
			lan.listeners = append(lan.listeners, listener)
			lan.urls = append(lan.urls, "http://"+listener.Addr().String())
			go func() { _ = lan.server.Serve(listener) }()
		}
	}
	if len(lan.urls) == 0 {
		return nil, errors.New("MODEL_GATEWAY_LAN_UNAVAILABLE")
	}
	return lan, nil
}

func (h *Handler) gatewayNetworkManagement(w http.ResponseWriter, r *http.Request) bool {
	if r.URL.Path != "/v1/model-gateway/network" {
		return false
	}
	s := h.Catalog
	if s == nil {
		reject(w, http.StatusServiceUnavailable, "MODEL_GATEWAY_UNAVAILABLE")
		return true
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	switch r.Method {
	case http.MethodGet:
	case http.MethodPut:
		var input struct {
			Enabled *bool `json:"enabled"`
		}
		if decodeBody(w, r, &input) != nil || input.Enabled == nil {
			reject(w, http.StatusBadRequest, "INVALID_MODEL_CATALOG")
			return true
		}
		enabled := *input.Enabled
		if enabled == s.value.LANEnabled && (h.lan != nil || !enabled) {
			break
		}
		var lan *gatewayLAN
		if enabled {
			var err error
			lan, err = h.openGatewayLAN(s.value.Port)
			if err != nil {
				reject(w, http.StatusServiceUnavailable, err.Error())
				return true
			}
		}
		next := s.snapshot()
		next.LANEnabled = enabled
		err := s.persist(next)
		if s.value.LANEnabled == enabled {
			if h.lan != nil {
				h.lan.close()
			}
			h.lan = lan
		} else if lan != nil {
			lan.close()
		}
		if err != nil {
			reject(w, http.StatusServiceUnavailable, "MODEL_GATEWAY_STORAGE_FAILED")
			return true
		}
	default:
		reject(w, http.StatusMethodNotAllowed, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return true
	}
	addresses := []string{}
	if h.lan != nil {
		addresses = h.lan.urls
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"enabled": s.value.LANEnabled, "urls": addresses}})
	return true
}
