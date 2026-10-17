package main

import (
	"errors"
	"os/exec"
)

// asExitError 单拎出来：errors.As 要的是 **T，内联写在 forward 里读着更绕。
func asExitError(err error, target **exec.ExitError) bool {
	return errors.As(err, target)
}
