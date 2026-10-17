package runtime

import (
	"os"
	"strings"
)

func tailFile(path string, maxLines int) ([]byte, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	lines := strings.Split(string(b), "\n")
	if len(lines) > maxLines {
		lines = lines[len(lines)-maxLines:]
	}
	return []byte(strings.Join(lines, "\n")), nil
}
