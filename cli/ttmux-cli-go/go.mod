module ttmux-cli-go

go 1.22

require (
	github.com/larksuite/oapi-sdk-go/v3 v3.9.8 // indirect
	modernc.org/sqlite v1.30.2
)

require (
	github.com/dustin/go-humanize v1.0.1 // indirect
	github.com/gogo/protobuf v1.3.2 // indirect
	github.com/google/uuid v1.6.0 // indirect
	github.com/gorilla/websocket v1.5.0 // indirect
	github.com/hashicorp/golang-lru/v2 v2.0.7 // indirect
	github.com/mattn/go-isatty v0.0.20 // indirect
	github.com/ncruces/go-strftime v0.1.9 // indirect
	github.com/remyoudompheng/bigfft v0.0.0-20230129092748-24d4a6f8daec // indirect
	golang.org/x/sys v0.19.0 // indirect
	modernc.org/gc/v3 v3.0.0-20240107210532-573471604cb6 // indirect
	modernc.org/libc v1.52.1 // indirect
	modernc.org/mathutil v1.6.0 // indirect
	modernc.org/memory v1.8.0 // indirect
	modernc.org/strutil v1.2.0 // indirect
	modernc.org/token v1.1.0 // indirect
)

require (
	roam-plugins/cron v0.0.0
	roam-plugins/hostmonitor v0.0.0
	roam-plugins/im v0.0.0
	roam-plugins/keepalive v0.0.0
	roam-plugins/reviewmesh v0.0.0
)

replace (
	roam-plugins/hostmonitor => ../../plugins/hostmonitor
	roam-plugins/im => ../../plugins/im
	roam-plugins/reviewmesh => ../../plugins/reviewmesh
)

replace roam-plugins/cron => ../../plugins/cron

replace roam-plugins/keepalive => ../../plugins/keepalive
