package agentproviders

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/tailscale/hujson"
)

func jsonDocument(data []byte) (map[string]any, error) {
	if len(data) == 0 {
		return map[string]any{}, nil
	}
	value, err := hujson.Parse(append([]byte{}, data...))
	if err != nil {
		return nil, fmt.Errorf("AGENT_CONFIG_INVALID")
	}
	if err := uniqueJSONKeys(value); err != nil {
		return nil, err
	}
	value.Standardize()
	var result map[string]any
	if json.Unmarshal(value.Pack(), &result) != nil || result == nil {
		return nil, fmt.Errorf("AGENT_CONFIG_INVALID")
	}
	return result, nil
}

func uniqueJSONKeys(value hujson.Value) error {
	switch node := value.Value.(type) {
	case *hujson.Object:
		seen := map[string]bool{}
		for _, member := range node.Members {
			key, ok := member.Name.Value.(hujson.Literal)
			if !ok || seen[key.String()] {
				return fmt.Errorf("AGENT_CONFIG_INVALID")
			}
			seen[key.String()] = true
			if err := uniqueJSONKeys(member.Value); err != nil {
				return err
			}
		}
	case *hujson.Array:
		for _, element := range node.Elements {
			if err := uniqueJSONKeys(element); err != nil {
				return err
			}
		}
	}
	return nil
}

func patchJSON(data []byte, path []string, next json.RawMessage) ([]byte, error) {
	if len(data) == 0 {
		data = []byte("{}\n")
	}
	if _, err := jsonDocument(data); err != nil {
		return nil, err
	}
	value, err := hujson.Parse(append([]byte{}, data...))
	if err != nil {
		return nil, fmt.Errorf("AGENT_CONFIG_INVALID")
	}
	pointer := ""
	for i, key := range path {
		pointer += "/" + strings.ReplaceAll(strings.ReplaceAll(key, "~", "~0"), "/", "~1")
		current := value.Find(pointer)
		if i < len(path)-1 {
			if current != nil {
				if _, ok := current.Value.(*hujson.Object); !ok {
					return nil, fmt.Errorf("AGENT_CONFIG_INVALID")
				}
				continue
			}
			if next == nil {
				return data, nil
			}
			patch := jsonValue([]any{map[string]any{"op": "add", "path": pointer, "value": map[string]any{}}})
			if value.Patch(patch) != nil {
				return nil, fmt.Errorf("AGENT_CONFIG_INVALID")
			}
			continue
		}
		if next == nil && current == nil {
			return data, nil
		}
		op := "add"
		if next == nil {
			op = "remove"
		}
		patch := jsonValue([]any{map[string]any{"op": op, "path": pointer, "value": next}})
		if value.Patch(patch) != nil {
			return nil, fmt.Errorf("AGENT_CONFIG_INVALID")
		}
	}
	return value.Pack(), nil
}
