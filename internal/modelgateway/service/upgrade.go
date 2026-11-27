package service

import (
	"net/http"
	"time"

	"github.com/ybz21/Roami/internal/modelgateway/httpapi"
)

type upgradeAdmission struct {
	lease    string
	expires  time.Time
	inFlight int
}

func (h *Handler) beginModelRequest(w http.ResponseWriter) bool {
	h.mu.Lock()
	closing := h.closing
	upgrading := time.Now().Before(h.upgrade.expires)
	if !closing && !upgrading {
		h.upgrade.inFlight++
	}
	h.mu.Unlock()

	if closing {
		httpapi.Reject(w, http.StatusServiceUnavailable, "MODEL_GATEWAY_UNAVAILABLE")
		return false
	}
	if upgrading {
		w.Header().Set("Retry-After", "5")
		httpapi.Reject(w, http.StatusServiceUnavailable, "MODEL_GATEWAY_UPGRADING")
		return false
	}
	return true
}

func (h *Handler) finishModelRequest() {
	h.mu.Lock()
	h.upgrade.inFlight--
	h.mu.Unlock()
}

// Upgrade admission is reachable only through the private management listener.
func (h *Handler) upgradeManagement(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		httpapi.Reject(w, http.StatusMethodNotAllowed, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return
	}
	var input httpapi.UpgradeRequest
	if httpapi.DecodeJSON(w, r, &input) != nil || len(input.Lease) > 128 {
		httpapi.Reject(w, http.StatusBadRequest, "INVALID_MODEL_GATEWAY_UPGRADE")
		return
	}

	h.mu.Lock()
	now := time.Now()
	owned := now.Before(h.upgrade.expires) && h.upgrade.lease == input.Lease
	code := ""
	status := http.StatusConflict
	switch input.Action {
	case "begin":
		if input.Lease == "" {
			code, status = "INVALID_MODEL_GATEWAY_UPGRADE", http.StatusBadRequest
		} else if now.Before(h.upgrade.expires) && !owned {
			code = "MODEL_GATEWAY_UPGRADE_ACTIVE"
		} else if !owned {
			h.upgrade.lease = input.Lease
			h.upgrade.expires = now.Add(2 * time.Minute)
		}
	case "status":
		if !owned {
			code = "MODEL_GATEWAY_UPGRADE_EXPIRED"
		}
	case "resume":
		if input.Lease == "" || owned {
			h.upgrade.lease = ""
			h.upgrade.expires = time.Time{}
		}
	default:
		code, status = "INVALID_MODEL_GATEWAY_UPGRADE", http.StatusBadRequest
	}
	view := httpapi.UpgradeState{Active: h.upgrade.inFlight}
	h.mu.Unlock()

	if code != "" {
		httpapi.Reject(w, status, code)
		return
	}
	httpapi.WriteJSON(w, http.StatusOK, map[string]any{"data": view})
}
