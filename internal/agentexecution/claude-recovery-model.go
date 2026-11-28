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
	gateway, err := s.claudeFreeGateway(ctx, model)
	return strings.TrimRight(gateway.BaseURL, "/"), err
}

func (s Service) claudeFreeGateway(ctx context.Context, model string) (claudeGatewayCatalog, error) {
	if !catalog.ValidID(model) {
		return claudeGatewayCatalog{}, errors.New("SESSION_RECOVERY_MODEL_NOT_AVAILABLE")
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
	if err := recoveryGatewayRead(ctx, client, "/v1/model-gateway/models?free=true", &models); err != nil {
		return claudeGatewayCatalog{}, err
	}
	for _, row := range models.Data.Models {
		if row.ID != model || !configuredFreeModel(row) {
			continue
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
	return claudeGatewayCatalog{}, errors.New("SESSION_RECOVERY_MODEL_NOT_AVAILABLE")
}

func configuredFreeModel(row directory.Row) bool {
	return row.Configured && row.Enabled && !row.GatewayHidden && (row.FreeOnly || row.Pricing == "confirmed-free")
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
