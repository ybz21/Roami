package agentproviders

import (
	"bytes"
	"encoding/json"
	"fmt"
	"reflect"
	"strings"

	"github.com/pelletier/go-toml/v2"
	"github.com/pelletier/go-toml/v2/unstable"
)

func tomlDocument(data []byte) (map[string]any, error) {
	result := map[string]any{}
	if toml.Unmarshal(data, &result) != nil {
		return nil, fmt.Errorf("AGENT_CONFIG_INVALID")
	}
	return result, nil
}

func nodeKeys(node *unstable.Node) []string {
	result := []string{}
	keys := node.Key()
	for keys.Next() {
		result = append(result, string(keys.Node().Data))
	}
	return result
}

func patchTOML(data []byte, path []string, next json.RawMessage) ([]byte, error) {
	if _, err := tomlDocument(data); err != nil {
		return nil, err
	}
	var replacement string
	if next != nil {
		var text string
		if json.Unmarshal(next, &text) != nil {
			return nil, fmt.Errorf("AGENT_CONFIG_INVALID")
		}
		replacement = string(jsonValue(text))
	}
	parent, key := path[:len(path)-1], path[len(path)-1]
	var parser unstable.Parser
	parser.Reset(data)
	table := []string{}
	insert := -1
	if len(parent) == 0 {
		insert = 0
	}
	for parser.NextExpression() {
		node := parser.Expression()
		switch node.Kind {
		case unstable.Table, unstable.ArrayTable:
			keys := nodeKeys(node)
			first := node.Key()
			first.Next()
			start := int(first.Node().Raw.Offset)
			start = bytes.LastIndexByte(data[:start], '\n') + 1
			if reflect.DeepEqual(table, parent) && insert < 0 {
				insert = start
			}
			table = keys
		case unstable.KeyValue:
			keys := nodeKeys(node)
			full := append(append([]string{}, table...), keys...)
			if !reflect.DeepEqual(full, path) {
				continue
			}
			value := node.Value()
			if value.Kind != unstable.String {
				return nil, fmt.Errorf("AGENT_CONFIG_INVALID")
			}
			start, end := int(value.Raw.Offset), int(value.Raw.Offset+value.Raw.Length)
			if next == nil {
				first := node.Key()
				first.Next()
				start = bytes.LastIndexByte(data[:first.Node().Raw.Offset], '\n') + 1
				if newline := bytes.IndexByte(data[end:], '\n'); newline >= 0 {
					end += newline + 1
				} else {
					end = len(data)
				}
			}
			return checkedTOML(append(append(append([]byte{}, data[:start]...), replacement...), data[end:]...))
		}
	}
	if parser.Error() != nil {
		return nil, fmt.Errorf("AGENT_CONFIG_INVALID")
	}
	if next == nil {
		return data, nil
	}
	if reflect.DeepEqual(table, parent) && insert < 0 {
		insert = len(data)
	}
	line := string(jsonValue(key)) + " = " + replacement + "\n"
	if insert >= 0 {
		prefix := []byte{}
		if insert > 0 && data[insert-1] != '\n' {
			prefix = append(prefix, '\n')
		}
		prefix = append(prefix, line...)
		return checkedTOML(append(append(append([]byte{}, data[:insert]...), prefix...), data[insert:]...))
	}
	parts := make([]string, len(parent))
	for i, part := range parent {
		parts[i] = string(jsonValue(part))
	}
	return checkedTOML(append(append([]byte{}, data...), []byte("\n["+strings.Join(parts, ".")+"]\n"+line)...))
}

func checkedTOML(data []byte) ([]byte, error) {
	if _, err := tomlDocument(data); err != nil {
		return nil, err
	}
	return data, nil
}
