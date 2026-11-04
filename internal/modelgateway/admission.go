package modelgateway

import (
	"context"
	"errors"
)

type admissionWaiter struct {
	changed chan struct{}
}

func (h *Handler) admit(ctx context.Context, role, model, session, request string, validate func() error, attribution ...CallAttribution) (Call, error) {
	h.mu.Lock()
	waiter := &admissionWaiter{}
	h.admissionQueue = append(h.admissionQueue, waiter)
	defer func() {
		h.dequeueAdmission(waiter)
		h.mu.Unlock()
	}()
	for {
		if err := ctx.Err(); err != nil {
			return Call{}, err
		}
		if h.closing {
			return Call{}, errors.New("MODEL_GATEWAY_UNAVAILABLE")
		}
		if err := validate(); err != nil {
			return Call{}, err
		}
		if h.admissionQueue[0] == waiter {
			call, err := h.Ledger.Admit(role, model, session, request, attribution...)
			if err == nil {
				h.activeForwards++
				return call, nil
			}
			// Only this handler's live requests can provide a settlement notification.
			if err.Error() != "MODEL_PROXY_USAGE_PENDING" || h.activeForwards == 0 {
				return Call{}, err
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
