package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"net/url"
	"os"

	"github.com/ybz21/Roami/internal/agentruntime"
)

func runAgentReminder(args []string) int {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" || args[0] == "-h" {
		fmt.Println("roami agent reminder ls\nroami agent reminder add --conversation ID --key KEY --text TEXT --after-seconds N\nroami agent reminder add --conversation ID --key KEY --text TEXT --daily-at HH:MM --timezone IANA\nroami agent reminder add --conversation ID --key KEY --text TEXT --when-ms EPOCH_MS\nroami agent reminder cancel --id ID")
		return 0
	}
	sub := args[0]
	if sub != "ls" && sub != "add" && sub != "cancel" {
		fmt.Fprintln(os.Stderr, "unknown agent reminder command")
		return 2
	}
	flags := flag.NewFlagSet("agent reminder "+sub, flag.ContinueOnError)
	cid := flags.String("conversation", "", "original conversation ID")
	key := flags.String("key", "", "required stable request key")
	text := flags.String("text", "", "reminder text")
	file := flags.String("file", "", "reminder text file, or - for stdin")
	id := flags.String("id", "", "reminder ID")
	after := flags.Int64("after-seconds", 0, "relative delay in seconds")
	when := flags.Int64("when-ms", -1, "UTC epoch milliseconds")
	daily := flags.String("daily-at", "", "daily local HH:MM")
	timezone := flags.String("timezone", "UTC", "IANA timezone for daily reminder")
	_ = flags.Bool("json", true, "JSON output")
	if err := flags.Parse(args[1:]); err != nil || flags.NArg() != 0 {
		return 2
	}
	method, path := "GET", "/v1/reminders"
	var body any
	if sub == "add" {
		count := 0
		for _, selected := range []bool{*after != 0, *when != -1, *daily != ""} {
			if selected {
				count++
			}
		}
		if *cid == "" || *key == "" || count != 1 {
			fmt.Fprintln(os.Stderr, "--conversation, --key and exactly one schedule are required")
			return 2
		}
		content, err := agentInput(*file, *text)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		spec := map[string]any{"conversationId": *cid, "requestKey": *key, "text": string(content), "timezone": *timezone}
		if *after != 0 {
			spec["afterSeconds"] = *after
		} else if *when != -1 {
			spec["whenMs"] = *when
		} else {
			spec["dailyAt"] = *daily
		}
		method, body = "POST", spec
	} else if sub == "cancel" {
		if *id == "" {
			fmt.Fprintln(os.Stderr, "--id is required")
			return 2
		}
		method, path = "DELETE", path+"/"+url.PathEscape(*id)
	}
	return agentSettingsRequest(method, path, body)
}

func runAgentNotificationPreferences(args []string) int {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" || args[0] == "-h" {
		fmt.Println("roami agent notification-preferences get\nroami agent notification-preferences set --file SETTINGS.json\nset replaces the complete settings object; use get as the starting point.")
		return 0
	}
	sub := args[0]
	if sub != "get" && sub != "set" {
		fmt.Fprintln(os.Stderr, "unknown notification preferences command")
		return 2
	}
	flags := flag.NewFlagSet("agent notification-preferences "+sub, flag.ContinueOnError)
	file := flags.String("file", "", "complete settings JSON file, or - for stdin")
	_ = flags.Bool("json", true, "JSON output")
	if err := flags.Parse(args[1:]); err != nil || flags.NArg() != 0 {
		return 2
	}
	method := "GET"
	var body any
	if sub == "set" {
		if *file == "" {
			fmt.Fprintln(os.Stderr, "--file is required")
			return 2
		}
		raw, err := agentInput(*file, "")
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		var settings map[string]any
		if err := json.Unmarshal(raw, &settings); err != nil || settings == nil {
			fmt.Fprintln(os.Stderr, "settings must be a JSON object")
			return 2
		}
		method, body = "PUT", map[string]any{"settings": settings}
	}
	return agentSettingsRequest(method, "/v1/notification-preferences", body)
}

func agentSettingsRequest(method, path string, body any) int {
	paths, err := agentruntime.Resolve("", "")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	raw, err := agentRequest(paths.Socket, method, path, body)
	if len(raw) > 0 {
		fmt.Println(string(raw))
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}
