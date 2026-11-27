package service

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net"
	"net/http"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/modelgateway/accounting"
	modelcatalog "github.com/ybz21/Roami/internal/modelgateway/catalog"
	"github.com/ybz21/Roami/internal/modelgateway/httpapi"
	wireprotocol "github.com/ybz21/Roami/internal/modelgateway/protocol"
	"github.com/ybz21/Roami/internal/modelgateway/routing"
	"github.com/ybz21/Roami/internal/modelgateway/upstream"
	"github.com/ybz21/Roami/internal/modelplugins"
)

func (h *Handler) forwardCatalog(w http.ResponseWriter, r *http.Request, catalog ModelCatalog, kind, protocol string, checks ...func() error) {
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 32<<20))
	var payload map[string]json.RawMessage
	if err != nil || json.Unmarshal(body, &payload) != nil {
		httpapi.Reject(w, 400, "INVALID_MODEL_CONFIG")
		return
	}
	var alias string
	_ = json.Unmarshal(payload["model"], &alias)
	var model *CatalogModel
	resolvedID := catalog.catalogModelID(kind, alias)
	if resolvedID == gatewayDefaultModel && catalogProtocol(kind, protocol) {
		model = h.Catalog.defaultModel(catalog)
	}
	if configured := catalog.findGatewayModel(resolvedID); configured != nil {
		copy := *configured
		model = &copy
	}
	probe, _ := r.Context().Value(qualityProbeContext{}).(*qualityProbe)
	if model == nil || probe == nil && model.HiddenAtGateway(modelcatalog.HiddenGatewayMembers(catalog.Models)) {
		httpapi.Reject(w, 400, "MODEL_NOT_CONFIGURED")
		return
	}
	observed := &observedRequestWriter{ResponseWriter: w}
	trace := newRequestObservation(observed, catalog, *model, kind)
	if probe != nil {
		probe.Trace = trace
	}
	w = observed
	defer trace.finish(r, observed, h)
	if !model.IsEnabled() {
		httpapi.Reject(w, 503, "MODEL_ROUTE_DISABLED")
		return
	}
	var freeOnlyRequested bool
	if raw, present := payload["roami_free_only"]; present {
		if json.Unmarshal(raw, &freeOnlyRequested) != nil {
			httpapi.Reject(w, 400, "INVALID_MODEL_CONFIG")
			return
		}
		delete(payload, "roami_free_only")
		body, _ = json.Marshal(payload)
		if freeOnlyRequested {
			model.FreeOnly, model.AllowPlan = true, false
		}
	}
	if model.FreeOnly && !model.Aggregate {
		model.Aggregate, model.Strategy = true, "order"
	}
	// Stateful provider IDs are not portable across sources or policy revisions.
	if raw := payload["previous_response_id"]; len(raw) > 0 && string(raw) != "null" {
		httpapi.Reject(w, 400, "MODEL_GATEWAY_CONTINUATION_UNSUPPORTED")
		return
	}
	sources := map[string]ModelSource{}
	for _, s := range catalog.Sources {
		sources[s.ID] = s
	}
	var choice *routing.Choice
	if model.Aggregate {
		required := ""
		if r.URL.Path == "/v1/responses/compact" {
			required = protocol
		}
		choice, err = h.newRoutingChoice(r.Context(), catalog, *model, required, false)
		if err != nil {
			httpapi.Reject(w, 503, "MODEL_ROUTE_UNAVAILABLE")
			return
		}
	}
	var admissionDuration time.Duration
	for index := 0; ; index++ {
		var leaf routing.Leaf
		if choice != nil {
			var ok bool
			leaf, ok, err = choice.Next()
			if err != nil {
				httpapi.Reject(w, 503, "MODEL_ROUTE_STATE_FAILED")
				return
			}
			if !ok {
				if trace.Attempts == 0 {
					trace.Blocks = choice.UnavailableReasons()
					if index == 0 && model.FreeOnly {
						wait := choice.NextAvailableAt().Sub(h.state.now())
						if wait > 0 {
							seconds := (wait-time.Nanosecond)/time.Second + 1
							w.Header().Set("Retry-After", strconv.FormatInt(int64(seconds), 10))
						}
					}
				}
				httpapi.Reject(w, 503, "MODEL_ROUTE_NO_AVAILABLE_MEMBER")
				return
			}
		} else {
			if index >= len(model.Candidates) {
				return
			}
			leaf.Candidate = model.Candidates[index]
		}
		candidate := leaf.Candidate
		if leaf.ChannelID == "" {
			leaf.ChannelID = candidate.Identity() + "/"
		}

		source, exists := sources[candidate.SourceID]
		if !exists {
			httpapi.Reject(w, 400, "MODEL_NOT_CONFIGURED")
			return
		}

		var pluginSource modelplugins.Source
		var pluginProvider modelplugins.Provider
		var pluginModel modelplugins.Model
		upstreamModel := candidate.Model
		if source.PluginSourceID != "" {
			if h.Plugins == nil {
				httpapi.Reject(w, 503, "MODEL_PLUGIN_UNAVAILABLE")
				return
			}
			pluginSource, err = h.Plugins.ReadSource(source.PluginSourceID)
			if err != nil {
				httpapi.Reject(w, 503, "MODEL_PLUGIN_UNAVAILABLE")
				return
			}
			pluginProvider, err = h.Plugins.CachedProvider(pluginSource)
			if err != nil {
				httpapi.Reject(w, 503, "MODEL_PLUGIN_MODELS_REQUIRED")
				return
			}
			found := false
			for _, m := range pluginProvider.Models {
				if m.ID == candidate.Model {
					pluginModel = m
					found = true
					break
				}
			}
			if !found {
				httpapi.Reject(w, 400, "MODEL_NOT_CONFIGURED")
				return
			}
			if modelplugins.DesktopUnavailable(pluginSource.ProviderID) {
				httpapi.Reject(w, 503, "MODEL_PLUGIN_DESKTOP_UNAVAILABLE")
				return
			}
			if modelplugins.DesktopAppMissing(pluginSource.ProviderID) {
				httpapi.Reject(w, 503, "MODEL_PLUGIN_DESKTOP_APP_MISSING")
				return
			}
			if !pluginProvider.SignedIn {
				httpapi.Reject(w, 401, "MODEL_PLUGIN_SIGN_IN_REQUIRED")
				return
			}
			source.Protocol = modelplugins.ModelProtocol(pluginModel, pluginProvider)
			source.BaseURL = pluginModel.URL
			if source.BaseURL == "" {
				source.BaseURL = pluginProvider.API
			}
			source.BaseURL = strings.TrimRight(source.BaseURL, "/")
			if pluginModel.APIID != "" {
				upstreamModel = pluginModel.APIID
			}
		}
		if r.URL.Path == "/v1/responses/compact" && source.Protocol != protocol {
			httpapi.Reject(w, 400, "MODEL_GATEWAY_COMPACTION_UNSUPPORTED")
			return
		}
		// WorkBuddy requires streams even when an Anthropic caller expects one JSON response.
		streamUpstream := source.PluginSourceID != "" && pluginSource.ProviderID == "workbuddy" && protocol == "anthropic-messages" && source.Protocol == "openai-completions"
		upstreamBody, bridge, conversionError := wireprotocol.Prepare(body, protocol, source.Protocol, upstreamModel, streamUpstream)
		if conversionError != nil {
			httpapi.Reject(w, 400, wireprotocol.ErrorCode(conversionError))
			return
		}
		if bridge != nil {
			bridge.SetResponseModel(alias)
		}
		validate := func() error { return nil }
		if len(checks) > 0 {
			validate = checks[0]
		}
		role, session := "cli_"+kind, ""
		if strings.HasPrefix(kind, "roami_") {
			role = strings.TrimPrefix(kind, "roami_")
			session = r.Header.Get("X-Eval-Session-Id")
			if observed := r.Header.Get("X-Eval-accounting.Call-Role"); observed != "" {
				role = observed
			}
		}
		if len(role) > 100 || len(session) > 200 || len(r.Header.Get("X-Request-Id")) > 200 {
			httpapi.Reject(w, 400, "INVALID_MODEL_CONFIG")
			return
		}
		agentKind := kind
		if strings.HasPrefix(kind, "roami_") {
			agentKind = "roami"
		}
		keyID, _ := r.Context().Value(gatewayKeyContext{}).(string)
		if keyID != "" {
			check := validate
			validate = func() error {
				if err := check(); err != nil {
					return err
				}
				h.Catalog.mu.Lock()
				allowed := h.Catalog.keyAllowed(agentKind, keyID)
				h.Catalog.mu.Unlock()
				if !allowed {
					return errors.New("MODEL_GATEWAY_UNAUTHORIZED")
				}
				return nil
			}
		}
		admissionStarted := time.Now()
		call, e := h.admit(r.Context(), role, candidate.Model, session, r.Header.Get("X-Request-Id"), validate, accounting.CallAttribution{
			AgentKind: agentKind, KeyID: keyID, SourceID: source.ID, RouteID: model.ID, ObservationRequestID: trace.RequestID,
			Free: leaf.Free, PricingRevision: leaf.PricingRevision,
		})
		admissionDuration += time.Since(admissionStarted)
		w.Header().Set("X-Roami-Model-Admission-Ms", strconv.FormatInt(admissionDuration.Milliseconds(), 10))
		if e != nil {
			status := 503
			if e.Error() == "MODEL_GATEWAY_ROUTE_CHANGED" {
				status = 409
			}
			if e.Error() == "MODEL_GATEWAY_UNAUTHORIZED" {
				status = 401
			}
			if e.Error() == "MODEL_PROXY_DAILY_LIMIT" {
				status = 402
			}
			if strings.HasPrefix(e.Error(), "MODEL_PROXY_USAGE_") {
				status = 409
			}
			httpapi.Reject(w, status, e.Error())
			return
		}
		status, code, notSent := 0, "MODEL_GATEWAY_INTERRUPTED", false
		var usage *accounting.Usage
		// Each attempted source settles independently, including zero-send connection failures.
		attempt := func() bool {
			observation := wireprotocol.NewResponseObservation(source.Protocol, time.Now())
			delivered := false
			defer func() {
				record := h.observeAttempt(r, leaf, call, status, code, usage, observation, trace.RequestID, trace.Attempts+1)
				trace.attempt(record, candidate, usage, delivered, notSent)
			}()

			defer func() {
				if err := h.state.accounting.Settle(call, usage, status, code, notSent); err != nil {
					log.Printf("model gateway: settlement failed call=%s", call.ID)
				}
				h.releaseAdmission()
			}()
			suffix := r.URL.Path
			if bridge != nil {
				suffix = map[string]string{"openai-completions": "/v1/chat/completions", "openai-responses": "/v1/responses", "anthropic-messages": "/v1/messages"}[source.Protocol]
			}
			if source.PluginSourceID != "" || strings.HasSuffix(source.BaseURL, "/v1") {
				suffix = strings.TrimPrefix(suffix, "/v1")
			}
			out, e := http.NewRequestWithContext(r.Context(), "POST", source.BaseURL+suffix, bytes.NewReader(upstreamBody))
			if e != nil {
				notSent = true
				code = "INVALID_MODEL_CONFIG"
				httpapi.Reject(w, 400, code)
				return false
			}
			for name, values := range r.Header {
				lower := strings.ToLower(name)
				if slices.Contains([]string{"authorization", "cookie", "x-api-key", "api-key", "proxy-authorization", "connection", "upgrade", "content-length", "host"}, lower) || strings.HasPrefix(lower, "x-roami-") || strings.HasPrefix(lower, "x-eval-") {
					continue
				}
				if bridge != nil && (lower == "accept-encoding" || strings.HasPrefix(lower, "anthropic-") || strings.HasPrefix(lower, "openai-")) {
					continue
				}
				out.Header[name] = append([]string(nil), values...)
			}
			out.Header.Set("Content-Type", "application/json")
			if source.APIKey != "" {
				if source.Protocol == "anthropic-messages" && source.AuthMode == "api_key" {
					out.Header.Set("X-Api-Key", source.APIKey)
				} else {
					out.Header.Set("Authorization", "Bearer "+source.APIKey)
				}
			}
			if source.Protocol == "anthropic-messages" && out.Header.Get("Anthropic-Version") == "" {
				out.Header.Set("Anthropic-Version", "2023-06-01")
			}
			var response *http.Response
			if source.PluginSourceID != "" {
				response, e = h.Plugins.FetchAccount(r.Context(), pluginSource, pluginModel, pluginProvider, func() string {
					if leaf.Account != "" {
						return leaf.Account
					}
					return pluginSource.ProviderID
				}(), out, upstreamBody)
			} else {
				response, e = h.sourceClient(source).Do(out)
			}
			if e != nil {
				var op *net.OpError
				notSent = errors.As(e, &op) && op.Op == "dial"
				code = "MODEL_TRANSPORT_FAILED"
				if choice != nil {
					h.restRoute(leaf, *model, 0, 0)
				}
				if notSent && (choice != nil || model.Strategy == "failover" && index+1 < len(model.Candidates)) && r.Context().Err() == nil {
					return true
				}
				httpapi.Reject(w, 502, code)
				return false
			}
			defer response.Body.Close()
			response.Body = observation.Wrap(response.Body, strings.Contains(response.Header.Get("Content-Type"), "text/event-stream"))
			call.RecordUpstream(upstream.ResponseReceipt(response))
			status = response.StatusCode
			if choice != nil && upstreamRouteFailure(status) {
				h.restRoute(leaf, *model, status, upstream.RetryDelay(response.Header.Get("Retry-After"), h.state.now()))
				retry := true
				if status == 429 {
					retry = model.SwitchOnLimit()
				}
				if status == 402 {
					retry = model.SwitchOnExhausted()
				}
				if retry && r.Context().Err() == nil {
					n, readErr := io.Copy(io.Discard, io.LimitReader(response.Body, (4<<20)+1))
					code = "MODEL_HTTP_" + strconv.Itoa(status)
					notSent = readErr == nil && n <= 4<<20 && status < 500
					return true
				}
			}
			for name, values := range response.Header {
				lower := strings.ToLower(name)
				if strings.HasPrefix(lower, "x-roami-") || slices.Contains([]string{"connection", "transfer-encoding", "content-length", "set-cookie", "upgrade"}, lower) {
					continue
				}
				if bridge != nil && slices.Contains([]string{"content-type", "content-encoding"}, lower) {
					continue
				}
				w.Header()[name] = append([]string(nil), values...)
			}
			w.Header().Set("X-Roami-Model-Source", source.ID)
			w.Header().Set("X-Roami-Model-Alias", model.ID)
			w.Header().Set("X-Roami-Model-Call", call.ID)
			capture := wireprotocol.NewCapture(source.Protocol, strings.Contains(response.Header.Get("Content-Type"), "text/event-stream"))
			if bridge != nil {
				if status < 200 || status >= 300 {
					code = "MODEL_HTTP_" + strconv.Itoa(status)
					if status >= 300 && status < 500 {
						// Match native forwarding: only a complete rejection proves zero cost.
						n, readErr := io.Copy(io.Discard, io.LimitReader(response.Body, (4<<20)+1))
						notSent = readErr == nil && n <= 4<<20
					}
					bridge.WriteFailure(w, code, status)
					return false
				}
				complete, conversionError := bridge.Forward(w, response, capture)
				delivered = complete && conversionError == nil
				usage = capture.Finish(complete)
				if conversionError != nil {
					code = wireprotocol.ErrorCode(conversionError)
					status = 502
				} else {
					code = ""
				}
				return false
			}
			w.WriteHeader(status)
			buffer := make([]byte, 32<<10)
			complete := false
			for {
				n, re := response.Body.Read(buffer)
				if n > 0 {
					capture.Feed(buffer[:n])
					if _, e = w.Write(buffer[:n]); e != nil {
						break
					}
					if capture.Streaming() {
						if f, ok := w.(http.Flusher); ok {
							f.Flush()
						}
					}
				}
				if re != nil {
					complete = re == io.EOF
					break
				}
			}
			if status >= 200 && status < 300 {
				delivered = complete
				usage = capture.Finish(complete)
				if usage != nil {
					code = ""
				} else {
					code = "MODEL_PROXY_USAGE_UNKNOWN"
				}
			} else {
				code = "MODEL_HTTP_" + strconv.Itoa(status)
				notSent = complete && status >= 300 && status < 500
			}
			return false
		}
		if !attempt() {
			return
		}
	}
}

func upstreamRouteFailure(status int) bool {
	switch status {
	case http.StatusUnauthorized, http.StatusPaymentRequired, http.StatusForbidden, http.StatusNotFound, http.StatusRequestTimeout, http.StatusTooManyRequests:
		return true
	default:
		return status >= 500 && status < 600
	}
}
