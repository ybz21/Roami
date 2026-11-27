package httpapi

const UpgradePath = "/internal/installation/quiesce"

type UpgradeRequest struct {
	Action string `json:"action"`
	Lease  string `json:"lease,omitempty"`
}

type UpgradeState struct {
	Active int `json:"active"`
}
