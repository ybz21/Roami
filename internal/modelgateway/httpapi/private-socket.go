package httpapi

import (
	"errors"
	"os"

	"github.com/ybz21/Roami/internal/fsguard"
)

func PrivateSocket(agentSocket string) (string, error) {
	socket := Socket(agentSocket)
	info, err := os.Lstat(socket)
	if err != nil || info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0600 || !fsguard.OwnedByCurrentUser(info) {
		return "", errors.New("MODEL_GATEWAY_UNAVAILABLE")
	}
	return socket, nil
}
