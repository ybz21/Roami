package httpapi

import (
	"net/http"
	"slices"
	"strconv"
	"strings"

	"github.com/ybz21/Roami/internal/modelgateway/accounting"
)

func ServeAccounting(w http.ResponseWriter, r *http.Request, ledger *accounting.Ledger, notify func()) bool {
	if r.URL.Path == "/v1/model-gateway/settings" {
		switch r.Method {
		case "GET":
			c, err := ledger.Configuration()
			if err != nil {
				Reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
				return true
			}
			WriteJSON(w, 200, map[string]any{"data": c})
			return true
		case "PUT":
			c := accounting.DefaultConfiguration()
			c.Pricing.DefaultConfigured = nil
			if DecodeJSON(w, r, &c) != nil || c.Validate() != nil {
				Reject(w, 400, "INVALID_MODEL_PROXY_CONFIG")
				return true
			}
			scope := r.URL.Query().Get("scope")
			if !slices.Contains([]string{"", "pricing", "limits"}, scope) {
				Reject(w, 400, "INVALID_MODEL_PROXY_CONFIG")
				return true
			}
			if err := ledger.ConfigureScope(c, scope); err != nil {
				if err.Error() == "MODEL_PROXY_CURRENCY_MISMATCH" {
					Reject(w, 409, err.Error())
				} else {
					Reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
				}
				return true
			}
			notify()
			c, _ = ledger.Configuration()
			WriteJSON(w, 200, map[string]any{"data": c})
			return true
		}
	}
	if r.Method == "GET" && r.URL.Path == "/v1/model-gateway/usage" {
		if r.URL.Query().Get("view") != "" {
			q, err := accounting.ParseUsageQuery(r.URL.Query())
			if err != nil {
				Reject(w, 400, err.Error())
				return true
			}
			data, err := ledger.WorkspaceUsage(q)
			if err != nil {
				if strings.HasPrefix(err.Error(), "INVALID_") {
					Reject(w, 400, err.Error())
				} else {
					Reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
				}
				return true
			}
			WriteJSON(w, 200, map[string]any{"data": data})
			return true
		}
		days := 7
		if raw := r.URL.Query().Get("days"); raw != "" {
			var parseErr error
			days, parseErr = strconv.Atoi(raw)
			if parseErr != nil {
				Reject(w, 400, "INVALID_MODEL_USAGE_DAY")
				return true
			}
		}
		if days < 0 || days > 90 {
			Reject(w, 400, "INVALID_MODEL_USAGE_DAY")
			return true
		}
		data, err := ledger.StatisticsForCalls(days, r.URL.Query().Get("day"), r.URL.Query().Get("source"), r.URL.Query().Get("agentKind"), r.URL.Query().Get("recentState"))
		if err != nil {
			if err.Error() == "INVALID_MODEL_USAGE_DAY" || err.Error() == "INVALID_MODEL_USAGE_SOURCE" || err.Error() == "INVALID_AGENT_KIND" || err.Error() == "INVALID_MODEL_USAGE_STATE" {
				Reject(w, 400, err.Error())
				return true
			}
			Reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
			return true
		}
		WriteJSON(w, 200, map[string]any{"data": data})
		return true
	}
	if r.Method == "PUT" && strings.HasPrefix(r.URL.Path, "/v1/model-gateway/calls/") {
		id := strings.TrimPrefix(r.URL.Path, "/v1/model-gateway/calls/")
		var value struct {
			Amount *float64 `json:"amount"`
			Reason string   `json:"reason"`
		}
		if strings.Contains(id, "/") || DecodeJSON(w, r, &value) != nil || value.Amount == nil || !accounting.ValidAmount(*value.Amount) || strings.TrimSpace(value.Reason) == "" || len(value.Reason) > 500 {
			Reject(w, 400, "INVALID_MODEL_PROXY_CONFIG")
			return true
		}
		if err := ledger.Reconcile(id, *value.Amount, value.Reason); err != nil {
			if err.Error() == "MODEL_GATEWAY_CALL_NOT_UNKNOWN" {
				Reject(w, 409, err.Error())
			} else {
				Reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
			}
			return true
		}
		WriteJSON(w, 200, map[string]any{"data": map[string]string{"id": id}})
		return true
	}
	return false
}
