package modelgateway

import (
	"net/http"
	"regexp"
)

var upstreamRequestID = regexp.MustCompile(`^[A-Za-z0-9_.:-]{1,200}$`)

type upstreamReceipt struct {
	status  int
	request string
}

func responseReceipt(response *http.Response) upstreamReceipt {
	receipt := upstreamReceipt{status: response.StatusCode}
	for _, header := range []string{"X-Request-Id", "Request-Id"} {
		if value := response.Header.Get(header); upstreamRequestID.MatchString(value) {
			receipt.request = value
			break
		}
	}
	return receipt
}
