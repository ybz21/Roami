package upstream

import (
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"
)

var upstreamRequestID = regexp.MustCompile(`^[A-Za-z0-9_.:-]{1,200}$`)

func ResponseReceipt(response *http.Response) (int, string) {
	for _, header := range []string{"X-Request-Id", "Request-Id"} {
		if value := response.Header.Get(header); upstreamRequestID.MatchString(value) {
			return response.StatusCode, value
		}
	}
	return response.StatusCode, ""
}

func RetryDelay(value string, now time.Time) time.Duration {
	if seconds, err := strconv.ParseInt(strings.TrimSpace(value), 10, 64); err == nil && seconds > 0 {
		if seconds > int64((1<<63-1)/int64(time.Second)) {
			return time.Duration(1<<63 - 1)
		}
		return time.Duration(seconds) * time.Second
	}
	if at, err := http.ParseTime(value); err == nil && at.After(now) {
		return at.Sub(now)
	}
	return 0
}
