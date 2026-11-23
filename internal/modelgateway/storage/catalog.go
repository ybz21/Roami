// Package storage persists gateway state in the host metadata database.
package storage

import (
	"database/sql"

	metadb "github.com/ybz21/Roami/internal/storage"
)

func LoadCatalog(db *metadb.DB) (string, error) {
	var value string
	err := db.QueryRow(`SELECT value FROM gateway_catalog WHERE id=1`).Scan(&value)
	return value, err
}

func SaveCatalog(db *metadb.DB, value []byte, reconcile func(*sql.Tx) error) error {
	return db.Tx(func(tx *sql.Tx) error {
		if err := reconcile(tx); err != nil {
			return err
		}
		_, err := tx.Exec(`INSERT INTO gateway_catalog(id,value) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value`, string(value))
		return err
	})
}

func PruneRouteAnchors(tx *sql.Tx, retained map[string]bool) error {
	rows, err := tx.Query(`SELECT model_id FROM gateway_route_anchors`)
	if err != nil {
		return err
	}
	remove := []string{}
	for rows.Next() {
		var id string
		if err = rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		if !retained[id] {
			remove = append(remove, id)
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	for _, id := range remove {
		if _, err = tx.Exec(`DELETE FROM gateway_route_anchors WHERE model_id=?`, id); err != nil {
			return err
		}
	}
	return nil
}
