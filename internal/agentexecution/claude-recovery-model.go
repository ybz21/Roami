package agentexecution

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"strings"

	"github.com/ybz21/Roami/internal/agentproviders"
	"github.com/ybz21/Roami/internal/agentruntime"
	"github.com/ybz21/Roami/internal/modelgateway/catalog"
	"github.com/ybz21/Roami/internal/modelgateway/directory"
	"github.com/ybz21/Roami/internal/modelgateway/httpapi"
)

type claudeGatewayCatalog struct {
	BaseURL           string                 `json:"baseUrl"`
	Revision          string                 `json:"revision"`
	Models            []catalog.CatalogModel `json:"models"`
	QualifiedModelIDs map[string]string      `json:"qualifiedModelIds"`
}

func (s Service) claudeRecoveryGateway(ctx context.Context, model string) (string, error) {
	gateway, err := s.claudeGateway(ctx, model, false)
	return strings.TrimRight(gateway.BaseURL, "/"), err
}

func (s Service) claudeGateway(ctx context.Context, model string, allowMetered bool) (claudeGatewayCatalog, error) {
	return s.claudeGatewayRoutes(ctx, allowMetered, model)
}

func (s Service) claudeGatewayRoutes(ctx context.Context, allowMetered bool, requested ...string) (claudeGatewayCatalog, error) {
	unavailable := errors.New("SESSION_RECOVERY_MODEL_NOT_AVAILABLE")
	for _, model := range requested {
		if !catalog.ValidID(model) {
			return claudeGatewayCatalog{}, unavailable
		}
	}
	paths, err := agentruntime.Resolve(s.Runtime.HomeDir, s.Runtime.DataDir)
	if err != nil {
		return claudeGatewayCatalog{}, errors.New("SESSION_RECOVERY_GATEWAY_UNAVAILABLE")
	}
	socket, err := httpapi.PrivateSocket(paths.Socket)
	if err != nil {
		return claudeGatewayCatalog{}, errors.New("SESSION_RECOVERY_GATEWAY_UNAVAILABLE")
	}
	transport := agentruntime.Transport(socket)
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport}
	var models struct {
		Data struct {
			Models   []directory.Row `json:"models"`
			Revision string          `json:"revision"`
		} `json:"data"`
	}
	path := "/v1/model-gateway/models"
	if !allowMetered {
		path += "?free=true"
	}
	if err := recoveryGatewayRead(ctx, client, path, &models); err != nil {
		return claudeGatewayCatalog{}, err
	}
	eligible := make(map[string]bool, len(models.Data.Models))
	for _, row := range models.Data.Models {
		eligible[row.ID] = configuredGatewayModel(row, allowMetered)
	}
	for _, model := range requested {
		if !eligible[model] {
			return claudeGatewayCatalog{}, unavailable
		}
	}
	var gateway struct {
		Data claudeGatewayCatalog `json:"data"`
	}
	if err := recoveryGatewayRead(ctx, client, "/v1/model-gateway/catalog", &gateway); err != nil {
		return claudeGatewayCatalog{}, err
	}
	if gateway.Data.BaseURL == "" || models.Data.Revision == "" || models.Data.Revision != gateway.Data.Revision {
		return claudeGatewayCatalog{}, errors.New("SESSION_RECOVERY_GATEWAY_UNAVAILABLE")
	}
	return gateway.Data, nil
}

func configuredGatewayModel(row directory.Row, allowMetered bool) bool {
	return row.Configured && row.Enabled && !row.GatewayHidden &&
		(allowMetered || row.FreeOnly || row.Pricing == "confirmed-free")
}

func validateClassifierLaunch(spec Spec) error {
	if spec.ClassifierModel == "" && !spec.AllowMetered {
		return nil
	}
	if spec.Executor != "claude" || !spec.Persistent || !catalog.ValidID(spec.Model) ||
		!catalog.ValidID(spec.ClassifierModel) || spec.SessionID != "" && (spec.ResumeFrom == "" || spec.ResumeProvider == "") {
		return errors.New("INVALID_CLAUDE_CLASSIFIER_LAUNCH")
	}
	return nil
}

func (s Service) claudeLaunchRoutes(ctx context.Context, spec Spec, binding SessionBinding) (primary, classifier string, err error) {
	gateway, err := s.claudeGatewayRoutes(ctx, spec.AllowMetered, spec.Model, spec.ClassifierModel)
	if err != nil {
		return "", "", err
	}
	var profile struct {
		Environment map[string]string `json:"env"`
	}
	base := strings.TrimRight(gateway.BaseURL, "/")
	envBase := strings.TrimRight(os.Getenv("ANTHROPIC_BASE_URL"), "/")
	if json.Unmarshal(readClaudeModelSettings(binding), &profile) != nil ||
		strings.TrimRight(profile.Environment["ANTHROPIC_BASE_URL"], "/") != base ||
		envBase != "" && envBase != base {
		return "", "", errors.New("SESSION_RECOVERY_GATEWAY_PROFILE_REQUIRED")
	}
	inference, err := claudePickerCatalogModel(gateway, spec.Model)
	if err != nil {
		return "", "", err
	}
	approval, err := claudePickerCatalogModel(gateway, spec.ClassifierModel)
	if err != nil {
		return "", "", err
	}
	return inference.NativeID, approval.NativeID, nil
}

func recoveryGatewayRead(ctx context.Context, client *http.Client, path string, output any) error {
	unavailable := errors.New("SESSION_RECOVERY_GATEWAY_UNAVAILABLE")
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://roami-gateway"+path, nil)
	if err != nil {
		return unavailable
	}
	request.Header.Set("X-Roami-Owner", "local")
	response, err := client.Do(request)
	if err != nil {
		return unavailable
	}
	defer response.Body.Close()
	const limit = 4 << 20
	body, err := io.ReadAll(io.LimitReader(response.Body, limit+1))
	if response.StatusCode != http.StatusOK || err != nil || len(body) > limit || json.Unmarshal(body, output) != nil {
		return unavailable
	}
	return nil
}

func (s Service) claudeRecoveryModel(ctx context.Context, model string) (string, error) {
	base, err := s.claudeRecoveryGateway(ctx, model)
	if err != nil {
		return "", err
	}
	view, err := agentproviders.NewStore(s.Runtime.DataDir).View(ctx, "claude")
	nativeModel := agentproviders.NativeModelID("claude", model, view)
	override := strings.TrimRight(os.Getenv("ANTHROPIC_BASE_URL"), "/")
	if err != nil || strings.TrimRight(view.Current.BaseURL, "/") != base || (override != "" && override != base) || nativeModel != agentproviders.ClaudeGatewayModelID(model) {
		return "", errors.New("SESSION_RECOVERY_GATEWAY_PROFILE_REQUIRED")
	}
	return nativeModel, nil
}
