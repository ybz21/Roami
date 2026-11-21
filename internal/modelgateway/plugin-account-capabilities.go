package modelgateway

import (
	"context"
	"net/http"
	"time"

	"github.com/ybz21/Roami/internal/modelplugins"
)

func (h *Handler) pluginAccountCapability(w http.ResponseWriter, r *http.Request, source modelplugins.Source, action string) {
	method := http.MethodGet
	if action == "check-in" {
		method = http.MethodPost
	}
	if r.Method != method {
		reject(w, http.StatusMethodNotAllowed, "METHOD_NOT_ALLOWED")
		return
	}
	if modelplugins.DesktopUnavailable(source.ProviderID) || modelplugins.DesktopAppMissing(source.ProviderID) {
		reject(w, http.StatusConflict, "MODEL_PLUGIN_DESKTOP_UNAVAILABLE")
		return
	}
	provider, err := h.pluginAccountProvider(r, source)
	if err != nil {
		pluginFailure(w, err)
		return
	}
	declared := map[string]bool{
		"usage":    provider.Usage,
		"check-in": provider.CheckIn != nil && *provider.CheckIn,
		"calls":    provider.Calls != nil && *provider.Calls,
	}
	if !declared[action] {
		reject(w, http.StatusNotFound, "MODEL_PLUGIN_CAPABILITY_UNAVAILABLE")
		return
	}
	if !provider.SignedIn {
		reject(w, http.StatusConflict, "MODEL_PLUGIN_SIGN_IN_FAILED")
		return
	}
	if action == "calls" {
		ctx, cancel := context.WithTimeout(r.Context(), 15*time.Second)
		defer cancel()
		calls, err := h.Plugins.RecentAccountCalls(ctx, source, time.Now())
		if err != nil {
			reject(w, http.StatusBadGateway, "MODEL_PLUGIN_CALLS_UNAVAILABLE")
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"data": calls})
		return
	}
	if action == "usage" {
		ctx, cancel := context.WithTimeout(r.Context(), 15*time.Second)
		defer cancel()
		quota, err := h.Plugins.AccountQuota(ctx, source, source.ProviderID)
		if err != nil || quota.Error != "" || quota.SignIn == "expired" {
			code := "MODEL_PLUGIN_QUOTA_UNAVAILABLE"
			if quota.SignIn == "expired" {
				code = "MODEL_PLUGIN_SIGN_IN_FAILED"
			}
			reject(w, http.StatusBadGateway, code)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"data": quota})
		return
	}
	result, err := h.Plugins.CheckIn(r.Context(), source)
	if err != nil {
		if err.Error() == "MODEL_PLUGIN_BUSY" {
			pluginFailure(w, err)
		} else {
			reject(w, http.StatusBadGateway, "MODEL_PLUGIN_CHECK_IN_UNCONFIRMED")
		}
		return
	}
	if result.Outcome == "claimed" || result.Outcome == "done" {
		h.routing.quota.invalidate(source.ID, source.ProviderID)
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": result})
}

func (h *Handler) pluginAccountProvider(r *http.Request, source modelplugins.Source) (modelplugins.Provider, error) {
	provider, err := h.Plugins.CachedProvider(source)
	// Upgrade cached providers missing capabilities returned by the host.
	if err != nil || r.URL.Query().Get("refresh") == "1" {
		return h.Plugins.Provider(r.Context(), source)
	}
	if provider.CheckIn == nil || provider.Calls == nil {
		if refreshed, refreshErr := h.Plugins.Provider(r.Context(), source); refreshErr == nil {
			return refreshed, nil
		}
	}
	return provider, nil
}
