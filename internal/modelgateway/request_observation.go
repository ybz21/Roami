package modelgateway

import (
	"mime"
	"net/http"
	"time"

	"github.com/google/uuid"
)

const requestHeader = "X-Roami-Model-Request"

type requestObservation struct {
	MonitorRecord
	started     time.Time
	previous    ModelCandidate
	succeeded   bool
	unknownSend bool
}

type observedRequestWriter struct {
	http.ResponseWriter
	status int
}

func (w *observedRequestWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }
func (w *observedRequestWriter) WriteHeader(status int) {
	if status >= 200 && w.status == 0 {
		w.status = status
	}
	w.ResponseWriter.WriteHeader(status)
}
func (w *observedRequestWriter) Write(data []byte) (int, error) {
	if w.status == 0 {
		w.status = http.StatusOK
	}
	return w.ResponseWriter.Write(data)
}
func (w *observedRequestWriter) Flush() {
	if w.status == 0 {
		w.status = http.StatusOK
	}
	_ = http.NewResponseController(w.ResponseWriter).Flush()
}

func newRequestObservation(w http.ResponseWriter, catalog ModelCatalog, model CatalogModel, caller string) *requestObservation {
	if caller == "roami_monitor" {
		return &requestObservation{}
	}
	id := uuid.NewString()
	w.Header().Set(requestHeader, id)
	return &requestObservation{
		MonitorRecord: MonitorRecord{
			RequestID: id, RouteID: model.ID, Model: model.Name,
			Caller: caller, Revision: catalog.Revision, Quality: "unchecked",
		},
		started: time.Now(),
	}
}

func (o *requestObservation) attempt(record MonitorRecord, candidate ModelCandidate, usage *Usage, delivered, notSent bool) {
	if o.Attempts > 0 {
		switch {
		case o.previous.SourceID != candidate.SourceID:
			o.Switch = "source"
		case o.Switch == "" && o.previous.Model != candidate.Model:
			o.Switch = "model"
		}
	}
	o.Attempts++
	o.previous = candidate
	o.SourceID, o.UpstreamModel = candidate.SourceID, candidate.Model
	o.succeeded = delivered && record.Success
	if o.succeeded {
		o.FirstToken = record.FirstToken
		if usage != nil {
			o.TokenUsage = &monitorTokenUsage{Input: usage.Input, Output: usage.Output}
		}
	}
	o.unknownSend = !notSent && record.Error == "MODEL_TRANSPORT_FAILED"
	o.Error = record.Error
}

func (o *requestObservation) finish(r *http.Request, w *observedRequestWriter, h *Handler) {
	if o.RequestID == "" {
		return
	}
	o.Status = w.status
	o.Duration = time.Since(o.started).Milliseconds()
	if code := w.Header().Get("X-Roami-Model-Error"); code != "" {
		o.Error = monitorError(code)
	}
	media, _, _ := mime.ParseMediaType(w.Header().Get("Content-Type"))
	switch {
	case o.succeeded:
		o.Outcome = "success"
		o.Success = true
		o.Error = ""
		if o.Switch != "" {
			o.Outcome = "recovered"
		}
	case r.Context().Err() != nil:
		o.Outcome = "cancelled"
	case o.Error == "MODEL_ROUTE_NO_AVAILABLE_MEMBER" && o.Attempts == 0:
		o.Outcome = "blocked"
	case o.Error == "MODEL_ROUTE_NO_AVAILABLE_MEMBER":
		o.Outcome = "exhausted"
	case o.Status >= 200 && o.Status < 300 && media == "text/event-stream":
		o.Outcome = "interrupted"
		o.Error = "MODEL_GATEWAY_INTERRUPTED"
	case o.unknownSend || o.Status == 0:
		o.Outcome = "unknown"
	default:
		o.Outcome = "failed"
	}
	if h.Monitor != nil {
		_ = h.Monitor.Append(o.MonitorRecord)
	}
}
