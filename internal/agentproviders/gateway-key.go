package agentproviders

import "context"

type gatewayKeyChange struct{ base, key string }

func (s *Store) ReplaceGatewayKey(ctx context.Context, kind, base, key, revision string) error {
	_, err := s.apply(ctx, kind, "", revision, false, false, gatewayKeyChange{base, key})
	return err
}
