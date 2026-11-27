package service

import (
	"context"
	"errors"

	"github.com/ybz21/Roami/internal/modelgateway/accounting"
)

type admissionWaiter struct {
	changed chan struct{}
}

func (h *Handler) admit(ctx context.Context, role, model, session, request string, validate func() error, attribution ...accounting.CallAttribution) (accounting.Call, error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	check := func() error {
		if err := ctx.Err(); err != nil {
			return err
		}
		if h.closing {
			return errors.New("MODEL_GATEWAY_UNAVAILABLE")
		}
		return validate()
	}
	if len(attribution) > 0 && attribution[0].Free && attribution[0].PricingRevision != "" {
		if err := check(); err != nil {
			return accounting.Call{}, err
		}
		call, err := h.state.accounting.AdmitConfirmedFree(role, model, session, request, attribution[0])
		if !errors.Is(err, accounting.ErrNotConfirmedFree) {
			if err == nil {
				h.activeForwards++
			}
			return call, err
		}
	}
	waiter := &admissionWaiter{}
	h.admissionQueue = append(h.admissionQueue, waiter)
	defer h.dequeueAdmission(waiter)
	for {
		if err := check(); err != nil {
			return accounting.Call{}, err
		}
		if h.admissionQueue[0] == waiter {
			call, err := h.state.accounting.Admit(role, model, session, request, attribution...)
			if err == nil {
				h.activeForwards++
				return call, nil
			}
			// Only this handler's live requests can provide a settlement notification.
			if err.Error() != "MODEL_PROXY_USAGE_PENDING" || h.activeForwards == 0 {
				return accounting.Call{}, err
			}
		}
		if waiter.changed == nil {
			waiter.changed = make(chan struct{})
		}
		changed := waiter.changed
		h.mu.Unlock()
		select {
		case <-changed:
		case <-ctx.Done():
		}
		h.mu.Lock()
	}
}

func (h *Handler) dequeueAdmission(waiter *admissionWaiter) {
	for index, queued := range h.admissionQueue {
		if queued != waiter {
			continue
		}
		copy(h.admissionQueue[index:], h.admissionQueue[index+1:])
		h.admissionQueue[len(h.admissionQueue)-1] = nil
		h.admissionQueue = h.admissionQueue[:len(h.admissionQueue)-1]
		if index == 0 {
			h.signalAdmission()
		}
		return
	}
}

func (h *Handler) notifyAdmission() {
	h.mu.Lock()
	defer h.mu.Unlock()
	for _, waiter := range h.admissionQueue {
		if waiter.changed != nil {
			close(waiter.changed)
			waiter.changed = nil
		}
	}
}

func (h *Handler) releaseAdmission() {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.activeForwards--
	h.signalAdmission()
}

func (h *Handler) signalAdmission() {
	if len(h.admissionQueue) > 0 && h.admissionQueue[0].changed != nil {
		close(h.admissionQueue[0].changed)
		h.admissionQueue[0].changed = nil
	}
}
