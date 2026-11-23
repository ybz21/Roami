// Package modelgateway provides the host entry points for the local model gateway.
package modelgateway

import (
	"github.com/ybz21/Roami/internal/modelgateway/directory"
	"github.com/ybz21/Roami/internal/modelgateway/httpapi"
	"github.com/ybz21/Roami/internal/modelgateway/service"
	metadb "github.com/ybz21/Roami/internal/storage"
)

type ModelDirectoryRow = directory.Row

func Socket(agentSocket string) string {
	return httpapi.Socket(agentSocket)
}

func Start(paths metadb.Paths, socket string) (func(), error) {
	return service.Start(paths, socket)
}
