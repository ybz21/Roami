package cron

import (
	"fmt"
	"strconv"
	"strings"
	"time"
	_ "time/tzdata"
)

func configuredJob(args map[string]string, previous *Job, now time.Time) (Job, error) {
	job := Job{Name: strings.TrimSpace(args["name"]), Cron: strings.TrimSpace(args["cron"]),
		Action: args["action"], Enabled: true, Timezone: strings.TrimSpace(args["timezone"]),
		Provider: args["provider"], Prompt: args["prompt"], Workdir: args["workdir"], Command: args["command"], Artifact: strings.TrimSpace(args["artifact"])}
	if job.Name == "" {
		return Job{}, fmt.Errorf("name is required")
	}
	if job.Action == "" {
		job.Action = "agent"
	}
	if state, provided := args["enabled"]; provided {
		enabled, err := strconv.ParseBool(strings.TrimSpace(state))
		if err != nil {
			return Job{}, fmt.Errorf("--enabled must be true or false")
		}
		if previous != nil && enabled != previous.Enabled {
			return Job{}, fmt.Errorf("use cron.enable or cron.disable to change an existing job")
		}
		job.Enabled = enabled
	}
	job.Interactive = strings.TrimSpace(args["interactive"]) == "true" || strings.TrimSpace(args["interactive"]) == "1"
	job.Notify = strings.TrimSpace(args["notify"]) == "true" || strings.TrimSpace(args["notify"]) == "1"
	if previous != nil {
		job.Runs, job.LastRun, job.Enabled = previous.Runs, previous.LastRun, previous.Enabled
		if _, provided := args["timezone"]; !provided {
			job.Timezone = previous.Timezone
		}
	}
	if err := validateAction(job); err != nil {
		return Job{}, err
	}
	next, err := nextRun(job, now)
	if err != nil {
		return Job{}, err
	}
	job.NextRun = next.Unix()
	return job, nil
}

func scheduleLocation(name string) (*time.Location, error) {
	if name == "" {
		return time.Local, nil
	}
	location, err := time.LoadLocation(name)
	if err != nil {
		return nil, fmt.Errorf("invalid timezone %q", name)
	}
	return location, nil
}
