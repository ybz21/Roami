package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"net/url"
	"os"
	"strconv"
	"strings"
	"text/tabwriter"

	"github.com/ybz21/Roami/internal/agentruntime"
	"github.com/ybz21/Roami/internal/modelgateway"
)

func runModel(args []string) int {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" || args[0] == "-h" {
		_ = groupHelpPage("model").Render(os.Stdout)
		return 0
	}
	if args[0] != "list" {
		fmt.Fprintln(os.Stderr, "unknown model command; use roami model --help")
		return 2
	}
	fs := newCommandFlags("model list")
	asJSON := fs.Bool("json", false, "JSON output")
	all := fs.Bool("all", false, "include cached upstream models that are not configured")
	refresh := fs.Bool("refresh", false, "refresh upstream capability metadata")
	free := fs.Bool("free", false, "only confirmed free models or saved free-only pools")
	capability := fs.String("capability", "", "filter by advertised capability")
	if err := fs.Parse(args[1:]); err != nil {
		if err == flag.ErrHelp {
			return 0
		}
		return 2
	}
	if fs.NArg() != 0 {
		fmt.Fprintln(os.Stderr, "unexpected positional arguments")
		return 2
	}
	valid := false
	for _, name := range []string{"", "text", "image", "audio", "video", "tools", "reasoning", "structuredOutput", "streaming"} {
		valid = valid || *capability == name
	}
	if !valid {
		fmt.Fprintln(os.Stderr, "unknown model capability")
		return 2
	}
	paths, err := agentruntime.Resolve("", "")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	query := url.Values{"all": {fmt.Sprint(*all)}, "refresh": {fmt.Sprint(*refresh)}, "free": {fmt.Sprint(*free)}, "capability": {*capability}}
	raw, err := agentRequest(modelgateway.Socket(paths.Socket), "GET", "/v1/model-gateway/models?"+query.Encode(), nil)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if *asJSON {
		fmt.Println(string(raw))
		return 0
	}
	var reply struct {
		Data struct {
			Models   []modelgateway.ModelDirectoryRow `json:"models"`
			Failures []string                         `json:"refreshFailures"`
		} `json:"data"`
	}
	if err = json.Unmarshal(raw, &reply); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	out := tabwriter.NewWriter(os.Stdout, 0, 4, 2, ' ', 0)
	fmt.Fprintln(out, "ID\tTYPE\tSTATE\tPRICE\tIMAGE\tTOOLS\tREASONING\tSTRUCTURED\tCONTEXT")
	for _, row := range reply.Data.Models {
		state := "upstream"
		if row.Configured {
			state = "enabled"
			if !row.Enabled {
				state = "disabled"
			}
		}
		fmt.Fprintf(out, "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n", row.ID, row.Kind, state, row.Pricing, row.Capabilities["image"].Support, row.Capabilities["tools"].Support, row.Capabilities["reasoning"].Support, row.Capabilities["structuredOutput"].Support, modelContextLabel(row.ContextWindow))
	}
	_ = out.Flush()
	if len(reply.Data.Failures) > 0 {
		fmt.Fprintln(os.Stderr, "metadata refresh failed for sources:", strings.Join(reply.Data.Failures, ", "))
	}
	return 0
}

func modelContextLabel(value int) string {
	if value <= 0 {
		return "unknown"
	}
	return strconv.Itoa(value)
}
