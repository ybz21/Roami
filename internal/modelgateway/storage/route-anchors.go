package storage

import (
	"database/sql"

	metadb "github.com/ybz21/Roami/internal/storage"
)

type RouteAnchors struct {
	DB *metadb.DB
}

func (s RouteAnchors) Load(modelID string) (fingerprint, anchor string) {
	_ = s.DB.QueryRow(`SELECT fingerprint,anchor FROM gateway_route_anchors WHERE model_id=?`, modelID).Scan(&fingerprint, &anchor)
	return
}

func (s RouteAnchors) Save(modelID, fingerprint, anchor string) error {
	return s.DB.Tx(func(tx *sql.Tx) error {
		_, err := tx.Exec(`INSERT INTO gateway_route_anchors(model_id,fingerprint,anchor) VALUES(?,?,?) ON CONFLICT(model_id) DO UPDATE SET fingerprint=excluded.fingerprint,anchor=excluded.anchor`, modelID, fingerprint, anchor)
		return err
	})
}
