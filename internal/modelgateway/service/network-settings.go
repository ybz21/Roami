package service

import (
	"errors"
	"net/http"

	"github.com/ybz21/Roami/internal/modelgateway/lan"
)

var errNetworkStorage = errors.New("MODEL_GATEWAY_STORAGE_FAILED")

type networkView struct {
	Enabled bool     `json:"enabled"`
	URLs    []string `json:"urls"`
}

type networkSettings struct {
	binding *lan.Listener // Protected by CatalogStore.mu.
}

func (n *networkSettings) view(s *CatalogStore) networkView {
	s.mu.Lock()
	defer s.mu.Unlock()
	return n.viewLocked(s.value.LANEnabled)
}

func (n *networkSettings) viewLocked(enabled bool) networkView {
	view := networkView{Enabled: enabled, URLs: []string{}}
	if n.binding != nil {
		view.URLs = n.binding.URLs()
	}
	return view
}

func (n *networkSettings) setEnabled(s *CatalogStore, handler http.Handler, enabled bool) (networkView, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if enabled == s.value.LANEnabled && (n.binding != nil || !enabled) {
		return n.viewLocked(enabled), nil
	}
	var binding *lan.Listener
	if enabled {
		var err error
		binding, err = lan.Listen(s.value.Port, handler)
		if err != nil {
			return networkView{}, err
		}
	}
	next := s.snapshot()
	next.LANEnabled = enabled
	err := s.persist(next)
	if s.value.LANEnabled == enabled {
		if n.binding != nil {
			n.binding.Close()
		}
		n.binding = binding
	} else if binding != nil {
		binding.Close()
	}
	if err != nil {
		return networkView{}, errNetworkStorage
	}
	return n.viewLocked(enabled), nil
}

func (n *networkSettings) restore(s *CatalogStore, handler http.Handler) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.value.LANEnabled {
		return nil
	}
	binding, err := lan.Listen(s.value.Port, handler)
	if err != nil {
		return err
	}
	n.binding = binding
	return nil
}

func (n *networkSettings) close(s *CatalogStore) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if n.binding != nil {
		n.binding.Close()
		n.binding = nil
	}
}
