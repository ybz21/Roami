// Package upstream owns HTTP clients and outbound request decoration.
package upstream

import (
	"crypto/tls"
	"net/http"
	"net/url"
	"strings"
)

func NewClients() (*http.Client, *http.Client) {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	unchecked := transport.Clone()
	if unchecked.TLSClientConfig == nil {
		unchecked.TLSClientConfig = &tls.Config{}
	}
	unchecked.TLSClientConfig.InsecureSkipVerify = true // Only selected by an explicit catalog source setting.
	noRedirect := func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	return &http.Client{Transport: transport, CheckRedirect: noRedirect}, &http.Client{Transport: unchecked, CheckRedirect: noRedirect}
}

func WithHeaders(client *http.Client, endpoint string, headers map[string]string) *http.Client {
	if len(headers) == 0 {
		return client
	}
	withHeaders := *client
	transport := client.Transport
	if transport == nil {
		transport = http.DefaultTransport
	}
	base, _ := url.Parse(endpoint)
	withHeaders.Transport = sourceHeaderTransport{RoundTripper: transport, endpoint: base, headers: headers}
	return &withHeaders
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
