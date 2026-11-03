package swarm

import (
	"fmt"
	"strconv"
	"strings"
)

type commandOptions struct {
	args     []string
	values   map[string][]string
	switches map[string]bool
}

func parseOptions(args []string, valueFlags, switchFlags string) (commandOptions, error) {
	result := commandOptions{values: map[string][]string{}, switches: map[string]bool{}}
	values, switches := map[string]bool{}, map[string]bool{"json": true}
	for _, name := range strings.Fields(valueFlags) {
		values[name] = true
	}
	for _, name := range strings.Fields(switchFlags) {
		switches[name] = true
	}
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if arg == "--" {
			result.args = append(result.args, args[i+1:]...)
			break
		}
		if !strings.HasPrefix(arg, "--") {
			if strings.HasPrefix(arg, "-") {
				return result, fmt.Errorf("unknown option: %s", arg)
			}
			result.args = append(result.args, arg)
			continue
		}
		name, value, hasValue := strings.Cut(strings.TrimPrefix(arg, "--"), "=")
		if switches[name] {
			if hasValue {
				return result, fmt.Errorf("--%s does not take a value", name)
			}
			result.switches[name] = true
			continue
		}
		if !values[name] {
			return result, fmt.Errorf("unknown option: --%s", name)
		}
		if !hasValue {
			i++
			if i >= len(args) || strings.HasPrefix(args[i], "--") {
				return result, fmt.Errorf("value required: --%s", name)
			}
			value = args[i]
		}
		if strings.TrimSpace(value) == "" {
			return result, fmt.Errorf("value required: --%s", name)
		}
		if name != "depends-on" && len(result.values[name]) > 0 {
			return result, fmt.Errorf("duplicate option: --%s", name)
		}
		result.values[name] = append(result.values[name], value)
	}
	return result, nil
}
func (o commandOptions) value(name string) string {
	if values := o.values[name]; len(values) > 0 {
		return values[0]
	}
	return ""
}
func (o commandOptions) required(name string) (string, error) {
	value := o.value(name)
	if value == "" {
		return "", fmt.Errorf("--%s is required", name)
	}
	return value, nil
}
func (o commandOptions) positive(name string) (int, error) {
	value, err := o.required(name)
	if err != nil {
		return 0, err
	}
	number, err := strconv.Atoi(value)
	if err != nil || number < 1 {
		return 0, fmt.Errorf("--%s must be a positive integer", name)
	}
	return number, nil
}
func (o commandOptions) arguments(min, max int) error {
	if len(o.args) < min || len(o.args) > max {
		return fmt.Errorf("expected %d..%d arguments, got %d; use roami swarm help", min, max, len(o.args))
	}
	return nil
}
