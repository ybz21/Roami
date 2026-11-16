package modelgateway

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
)

func routingPriceRevision(config Configuration) string {
	raw, _ := json.Marshal(struct {
		Currency string
		Pricing  PricingConfig
	}{config.Currency, config.Pricing})
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}
