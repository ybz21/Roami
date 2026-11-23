package modelgateway

import (
	"errors"
	"maps"
	"net/http"
	"net/url"
	"slices"
	"strings"

	"golang.org/x/net/http/httpguts"
)

const maxSourceHeaders = 16

func (s *ModelSource) hideHeaderValues() {
	s.HeaderNames = slices.Sorted(maps.Keys(s.Headers))
	s.Headers = nil
}

func validateSourceHeaders(source, previous ModelSource) (map[string]string, error) {
	sameEndpoint := source.BaseURL == previous.BaseURL
	if source.Headers == nil {
		if !sameEndpoint && len(previous.Headers) > 0 {
			return nil, errors.New("MODEL_HEADERS_REQUIRED_FOR_ENDPOINT")
		}
		return previous.Headers, nil
	}
	badHeader := errors.New("INVALID_MODEL_SOURCE_HEADERS")
	if len(source.Headers) > maxSourceHeaders {
		return nil, badHeader
	}
	headers := make(map[string]string, len(source.Headers))
	size := 0
	for name, value := range source.Headers {
		if len(name) > 128 || !httpguts.ValidHeaderFieldName(name) {
			return nil, badHeader
		}
		name = http.CanonicalHeaderKey(name)
		if _, duplicate := headers[name]; duplicate || reservedSourceHeader(strings.ToLower(name)) {
			return nil, badHeader
		}
		if value == "" {
			if !sameEndpoint && previous.Headers[name] != "" {
				return nil, errors.New("MODEL_HEADERS_REQUIRED_FOR_ENDPOINT")
			}
			value = previous.Headers[name]
		}
		if strings.TrimSpace(value) == "" || len(value) > 4096 || !httpguts.ValidHeaderFieldValue(value) {
			return nil, badHeader
		}
		size += len(name) + len(value)
		if size > 16<<10 {
			return nil, badHeader
		}
		headers[name] = value
	}
	return headers, nil
}

func reservedSourceHeader(name string) bool {
	switch name {
	case "authorization", "x-api-key", "api-key", "proxy-authorization",
		"host", "content-length", "content-type", "content-encoding", "accept-encoding",
		"connection", "proxy-connection", "keep-alive", "transfer-encoding", "upgrade", "te", "trailer",
		"forwarded", "x-real-ip":
		return true
	}
	return strings.HasPrefix(name, "x-roami-") || strings.HasPrefix(name, "x-forwarded-")
}

type sourceHeaderTransport struct {
	http.RoundTripper
	endpoint *url.URL
	headers  map[string]string
}

func (t sourceHeaderTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	if t.endpoint != nil && r.URL.Scheme == t.endpoint.Scheme && strings.EqualFold(r.URL.Host, t.endpoint.Host) {
		r = r.Clone(r.Context())
		if r.Header == nil {
			r.Header = make(http.Header)
		}
		for name, value := range t.headers {
			r.Header.Set(name, value)
		}
	}
	return t.RoundTripper.RoundTrip(r)
}
