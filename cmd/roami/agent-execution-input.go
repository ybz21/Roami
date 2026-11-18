package main

import (
	"fmt"
	"io"
	"os"
)

// Execution prompts carry the admitted conversation, rather than a short CLI message.
func executionSpecInput(file string) ([]byte, error) {
	var reader io.Reader = os.Stdin
	if file != "-" {
		input, err := os.Open(file)
		if err != nil {
			return nil, err
		}
		defer input.Close()
		reader = input
	}
	const limit = 8 << 20
	content, err := io.ReadAll(io.LimitReader(reader, limit+1))
	if err != nil {
		return nil, err
	}
	if len(content) > limit {
		return nil, fmt.Errorf("AGENT_INPUT_TOO_LARGE")
	}
	return content, nil
}
