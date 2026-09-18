// 会话守护插件——独立 Go 模块,经 replace 编译进 ttmux 二进制(builtin)。
module roam-plugins/keepalive

go 1.22

require ttmux-cli-go v0.0.0

replace ttmux-cli-go => ../../cli/ttmux-cli-go
