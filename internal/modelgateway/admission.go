package modelgateway

import (
	"context"
	"errors"
)

func (h *Handler) admit(ctx context.Context, role, model, session, request string, validate func() error, attribution ...CallAttribution) (Call, error) {
	for {
		h.mu.Lock()
		if err := ctx.Err(); err != nil {
			h.mu.Unlock()
			return Call{}, err
		}
		if h.closing {
			h.mu.Unlock()
			return Call{}, errors.New("MODEL_GATEWAY_UNAVAILABLE")
		}
		if err := validate(); err != nil {
			h.mu.Unlock()
			return Call{}, err
		}
		call, err := h.Ledger.Admit(role, model, session, request, attribution...)
		if err == nil {
			h.activeForwards++
			h.mu.Unlock()
			return call, nil
		}
		// Only this handler's live requests can provide a settlement notification.
		if err.Error() != "MODEL_PROXY_USAGE_PENDING" || h.activeForwards == 0 {
			h.mu.Unlock()
			return Call{}, err
		}
		if h.admissionChanged == nil {
			h.admissionChanged = make(chan struct{})
		}
		changed := h.admissionChanged
		h.mu.Unlock()
		select {
		case <-changed:
		case <-ctx.Done():
			return Call{}, ctx.Err()
		}
	}
}

func (h *Handler) notifyAdmission() {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.signalAdmission()
}

func (h *Handler) releaseAdmission() {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.activeForwards--
	h.signalAdmission()
}

func (h *Handler) signalAdmission() {
	if h.admissionChanged != nil {
		close(h.admissionChanged)
		h.admissionChanged = nil
	}
}
