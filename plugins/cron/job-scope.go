package cron

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"
)

var errJobScopeNotFound = errors.New("CRON_JOB_SCOPE_NOT_FOUND")

type jobScope map[string]bool

func schedulerScope(args map[string]string) (jobScope, error) {
	for key := range args {
		if key != "name" && key != "names" && key != "json" {
			return nil, fmt.Errorf("INVALID_CRON_JOB_SCOPE: unknown option %q", key)
		}
	}
	raw, present := args["names"]
	name, single := args["name"]
	if present && single {
		return nil, fmt.Errorf("INVALID_CRON_JOB_SCOPE: use --name or --names")
	}
	if !present && !single {
		return nil, nil
	}
	var names []string
	if single {
		names = []string{name}
	} else if err := json.Unmarshal([]byte(raw), &names); err != nil || len(names) == 0 {
		return nil, fmt.Errorf("INVALID_CRON_JOB_SCOPE: --names requires a nonempty JSON array")
	}
	scope := jobScope{}
	for _, name := range names {
		if name == "" || strings.TrimSpace(name) != name || scope[name] {
			return nil, fmt.Errorf("INVALID_CRON_JOB_SCOPE: names must be nonempty and unique")
		}
		scope[name] = true
	}
	return scope, nil
}

func (scope jobScope) validate(jobs []Job) error {
	for name := range scope {
		found := false
		for _, job := range jobs {
			if job.Name == name {
				found = true
				break
			}
		}
		if !found {
			return fmt.Errorf("%w: %s", errJobScopeNotFound, name)
		}
	}
	return nil
}
