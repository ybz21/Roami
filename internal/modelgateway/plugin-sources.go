package modelgateway

import (
	"bytes"
	"fmt"
	"io"
	"net/http"
	"strings"

	"github.com/ybz21/Roami/internal/modelplugins"
)

func pluginFailure(w http.ResponseWriter, err error) {
	code := err.Error()
	if !containsField([]string{"INVALID_MODEL_PLUGIN_PACKAGE", "MODEL_PLUGIN_DESKTOP_UNAVAILABLE", "MODEL_PLUGIN_DESKTOP_APP_MISSING", "MODEL_PLUGIN_DESKTOP_PACKAGE_UNTRUSTED", "MODEL_PLUGIN_BUN_UNAVAILABLE", "MODEL_PLUGIN_SANDBOX_UNAVAILABLE", "MODEL_PLUGIN_BUSY", "MODEL_PLUGIN_PROVIDER_NOT_FOUND", "MODEL_PLUGIN_SIGN_IN_FAILED", "MODEL_PLUGIN_MODELS_REQUIRED"}, code) {
		code = "MODEL_PLUGIN_FAILED"
	}
	reject(w, 400, code)
}
func publicProvider(p modelplugins.Provider) modelplugins.Provider {
	p.API = ""
	for i := range p.Models {
		p.Models[i].URL = ""
	}
	return p
}
func (h *Handler) pluginsManagement(w http.ResponseWriter, r *http.Request) bool {
	const route = "/v1/model-gateway/plugins"
	if r.URL.Path != route && !strings.HasPrefix(r.URL.Path, route+"/") {
		return false
	}
	if h.Plugins == nil || h.Catalog == nil {
		reject(w, 503, "MODEL_PLUGIN_UNAVAILABLE")
		return true
	}
	if r.Method == "GET" && r.URL.Path == route+"/packages" {
		writeJSON(w, 200, map[string]any{"data": h.Plugins.Packages()})
		return true
	}
	if r.Method == "POST" && r.URL.Path == route+"/import" {
		h.importModelPlugin(w, r)
		return true
	}
	if r.Method == "POST" && r.URL.Path == route+"/inspect" {
		var input struct {
			PackageID string `json:"packageId"`
		}
		if decodeBody(w, r, &input) != nil {
			reject(w, 400, "INVALID_MODEL_PLUGIN_PACKAGE")
			return true
		}
		providers, err := h.Plugins.Inspect(r.Context(), input.PackageID)
		if err != nil {
			pluginFailure(w, err)
			return true
		}
		for i := range providers {
			providers[i] = publicProvider(providers[i])
		}
		writeJSON(w, 200, map[string]any{"data": providers})
		return true
	}
	if r.Method == "POST" && r.URL.Path == route+"/sources" {
		var input struct {
			SourceID   string `json:"sourceId"`
			PackageID  string `json:"packageId"`
			ProviderID string `json:"providerId"`
			Revision   string `json:"revision"`
		}
		if decodeBody(w, r, &input) != nil {
			reject(w, 400, "INVALID_MODEL_PLUGIN_PACKAGE")
			return true
		}
		h.Catalog.mu.Lock()
		valid := h.Catalog.value.Revision == input.Revision && !h.Catalog.applying
		if input.SourceID != "" {
			owned := false
			for _, row := range h.Catalog.value.Sources {
				if row.PluginSourceID == input.SourceID {
					owned = true
					break
				}
			}
			if !owned {
				h.Catalog.mu.Unlock()
				reject(w, 404, "MODEL_PLUGIN_SOURCE_NOT_FOUND")
				return true
			}
			source, err := h.Plugins.ReadSource(input.SourceID)
			if err != nil {
				h.Catalog.mu.Unlock()
				pluginFailure(w, err)
				return true
			}
			input.PackageID, input.ProviderID = source.PackageID, source.ProviderID
		}
		h.Catalog.mu.Unlock()
		if !valid {
			reject(w, 409, "MODEL_CATALOG_CHANGED")
			return true
		}
		source, provider, err := h.Plugins.Create(r.Context(), input.PackageID, input.ProviderID)
		if err != nil {
			pluginFailure(w, err)
			return true
		}
		s := h.Catalog
		s.mu.Lock()
		defer s.mu.Unlock()
		next := s.snapshot()
		next.Revision = input.Revision
		name := provider.Name
		for number := 2; ; number++ {
			exists := false
			for _, row := range next.Sources {
				if row.Name == name {
					exists = true
					break
				}
			}
			if !exists {
				break
			}
			name = fmt.Sprintf("%s %d", provider.Name, number)
		}
		next.Sources = append(next.Sources, ModelSource{ID: source.ID, PluginSourceID: source.ID, Name: name})
		if err = s.update(r.Context(), next); err != nil {
			h.Plugins.Remove(source.ID)
			reject(w, 409, err.Error())
			return true
		}
		writeJSON(w, 200, map[string]any{"data": map[string]any{"catalog": s.view(r.Context()), "sourceId": source.ID}})
		return true
	}
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, route+"/sources/"), "/")
	if len(parts) < 2 || len(parts) > 3 {
		reject(w, 404, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return true
	}
	h.Catalog.mu.Lock()
	owned := false
	for _, s := range h.Catalog.value.Sources {
		if s.PluginSourceID == parts[0] {
			owned = true
			break
		}
	}
	h.Catalog.mu.Unlock()
	if !owned {
		reject(w, 404, "MODEL_PLUGIN_SOURCE_NOT_FOUND")
		return true
	}
	source, err := h.Plugins.ReadSource(parts[0])
	if err != nil {
		pluginFailure(w, err)
		return true
	}
	switch {
	case len(parts) == 2 && parts[1] == "info" && r.Method == "GET":
		provider, err := h.Plugins.CachedProvider(source)
		if err != nil || r.URL.Query().Get("refresh") == "1" {
			provider, err = h.Plugins.Provider(r.Context(), source)
		}
		if err != nil {
			pluginFailure(w, err)
			return true
		}
		writeJSON(w, 200, map[string]any{"data": map[string]any{"provider": publicProvider(provider), "options": source.Options, "desktopUnavailable": modelplugins.DesktopUnavailable(source.ProviderID), "desktopAppMissing": modelplugins.DesktopAppMissing(source.ProviderID)}})
	case len(parts) == 2 && parts[1] == "options" && r.Method == "POST":
		var input struct {
			Options map[string]any `json:"options"`
		}
		if decodeBody(w, r, &input) != nil {
			reject(w, 400, "INVALID_MODEL_PLUGIN_PACKAGE")
			return true
		}
		if err = h.Plugins.SetOptions(r.Context(), source, input.Options); err != nil {
			pluginFailure(w, err)
			return true
		}
		writeJSON(w, 200, map[string]any{"data": map[string]bool{"ok": true}})
	case len(parts) == 2 && parts[1] == "auth" && r.Method == "POST":
		var input struct {
			Action  string         `json:"action"`
			Method  int            `json:"method"`
			Key     string         `json:"key"`
			Inputs  map[string]any `json:"inputs"`
			Session string         `json:"session"`
			Code    string         `json:"code"`
			Value   any            `json:"value"`
		}
		if decodeBody(w, r, &input) != nil {
			reject(w, 400, "INVALID_MODEL_PLUGIN_PACKAGE")
			return true
		}
		if input.Action == "apiKey" {
			provider, err := h.Plugins.CachedProvider(source)
			if err != nil || input.Method < 0 || input.Method >= len(provider.Methods) || len(input.Key) > 8192 || strings.ContainsAny(input.Key, "\r\n\x00") || !provider.Methods[input.Method].Keyless && strings.TrimSpace(input.Key) == "" {
				reject(w, 400, "MODEL_PLUGIN_SIGN_IN_FAILED")
				return true
			}
		}
		params := map[string]any{"method": input.Method, "key": input.Key, "inputs": input.Inputs, "session": input.Session, "code": input.Code, "value": input.Value}
		if input.Action == "callback" {
			id, err := h.Plugins.BeginCallback(source, params)
			if err != nil {
				pluginFailure(w, err)
				return true
			}
			writeJSON(w, 202, map[string]any{"data": map[string]string{"jobId": id}})
			return true
		}
		var result modelplugins.AuthReply
		if err = h.Plugins.Auth(r.Context(), source, input.Action, params, &result); err != nil {
			pluginFailure(w, err)
			return true
		}
		if result.OK && input.Action == "apiKey" || input.Action == "signOut" {
			_, _ = h.Plugins.Provider(r.Context(), source)
		}
		result.Invalid = result.Error != ""
		result.Error = ""
		writeJSON(w, 200, map[string]any{"data": result})
	case len(parts) == 3 && parts[1] == "auth-jobs" && (r.Method == "GET" || r.Method == "DELETE"):
		result, err := h.Plugins.CallbackStatus(source.ID, parts[2], r.Method == "DELETE")
		if err != nil {
			reject(w, 404, "MODEL_PLUGIN_AUTH_NOT_FOUND")
			return true
		}
		writeJSON(w, 200, map[string]any{"data": result})
	default:
		reject(w, 404, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
	}
	return true
}
func (h *Handler) importModelPlugin(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, modelplugins.MaxExpandedBytes+(8<<20))
	files, paths, err := pluginUploadParts(r)
	if err != nil {
		pluginFailure(w, err)
		return
	}
	var imported modelplugins.Collection
	if len(files) == 1 && strings.HasSuffix(strings.ToLower(files[0].name), ".zip") && (len(paths) == 0 || len(paths) == 1 && paths[0] == "") {
		imported, err = modelplugins.ImportCollectionZIP(h.Plugins.PackagesRoot(), bytes.NewReader(files[0].data), int64(len(files[0].data)))
	} else {
		if len(paths) != len(files) {
			reject(w, 400, "INVALID_MODEL_PLUGIN_PACKAGE")
			return
		}
		uploads := []modelplugins.Upload{}
		for i, file := range files {
			uploads = append(uploads, modelplugins.Upload{Path: paths[i], Reader: bytes.NewReader(file.data)})
		}
		imported, err = modelplugins.ImportCollectionFolder(h.Plugins.PackagesRoot(), uploads)
	}
	if err != nil {
		pluginFailure(w, err)
		return
	}
	if len(imported.Packages) == 1 && len(imported.Skipped) == 0 {
		writeJSON(w, 200, map[string]any{"data": imported.Packages[0]})
	} else {
		writeJSON(w, 200, map[string]any{"data": imported})
	}
}

func (h *Handler) pluginAuthChanged(id string) error {
	s := h.Catalog
	s.mu.Lock()
	defer s.mu.Unlock()
	next := s.snapshot()
	for i, source := range next.Sources {
		if source.PluginSourceID == id {
			revision, err := randomCatalogID()
			if err != nil {
				return err
			}
			next.Sources[i].PluginRevision = revision
			return s.persist(next)
		}
	}
	return nil
}

type pluginUploadFile struct {
	name string
	data []byte
}

// Streaming parts preserves the advertised file limit beyond ReadForm's 1,000-part default.
func pluginUploadParts(r *http.Request) ([]pluginUploadFile, []string, error) {
	reader, err := r.MultipartReader()
	if err != nil {
		return nil, nil, modelplugins.ErrInvalidPackage
	}
	files, paths := []pluginUploadFile{}, []string{}
	total := 0
	for {
		part, err := reader.NextPart()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, nil, modelplugins.ErrInvalidPackage
		}
		limit := int64(1024)
		if part.FormName() == "files" {
			limit = modelplugins.MaxFileBytes
			if strings.HasSuffix(strings.ToLower(part.FileName()), ".zip") {
				limit = modelplugins.MaxArchiveBytes
			}
			if part.FileName() == "" || len(files) >= modelplugins.MaxFiles {
				part.Close()
				return nil, nil, modelplugins.ErrInvalidPackage
			}
		} else if part.FormName() != "paths" || len(paths) >= modelplugins.MaxFiles {
			part.Close()
			return nil, nil, modelplugins.ErrInvalidPackage
		}
		data, err := io.ReadAll(io.LimitReader(part, limit+1))
		_ = part.Close()
		if err != nil || int64(len(data)) > limit {
			return nil, nil, modelplugins.ErrInvalidPackage
		}
		if part.FormName() == "files" {
			total += len(data)
			if total > modelplugins.MaxExpandedBytes {
				return nil, nil, modelplugins.ErrInvalidPackage
			}
			files = append(files, pluginUploadFile{name: part.FileName(), data: data})
		} else {
			paths = append(paths, string(data))
		}
	}
	if len(files) == 0 {
		return nil, nil, modelplugins.ErrInvalidPackage
	}
	return files, paths, nil
}
