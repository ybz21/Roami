package okr

import (
	"bytes"
	_ "embed"
	"encoding/base64"
	"encoding/json"
	"net/url"
	"path"
	"strings"

	"golang.org/x/net/html"
)

func encodeDashboardAsset(body []byte) string { return base64.StdEncoding.EncodeToString(body) }

func dashboardReference(bundle *DashboardBundle, entry, reference, kind string) (string, error) {
	target, err := url.Parse(reference)
	if err != nil || target.IsAbs() || strings.HasPrefix(target.Path, "/") || target.Host != "" || target.RawQuery != "" || target.Fragment != "" || strings.ContainsAny(target.Path, `\\:%`) {
		return "", ErrInvalid
	}
	name := path.Clean(path.Join(path.Dir(entry), target.Path))
	asset, ok := bundle.Assets[name]
	if !ok || !strings.HasPrefix(name, "dashboard/") || asset.MIMEType != kind {
		return "", ErrInvalid
	}
	return dataURL(asset), nil
}

func dashboardMarkup(bundle *DashboardBundle) (string, error) {
	entry, ok := bundle.Assets[bundle.Entry]
	if !ok {
		return "", ErrInvalid
	}
	doc, err := html.Parse(bytes.NewReader(entry.Body))
	if err != nil {
		return "", ErrInvalid
	}
	var walk func(*html.Node) error
	walk = func(node *html.Node) error {
		if node.Type == html.ElementNode {
			switch node.Data {
			case "base", "iframe", "frame", "object", "embed", "form":
				return ErrInvalid
			}
			if node.Data == "meta" {
				for _, a := range node.Attr {
					if strings.EqualFold(a.Key, "http-equiv") {
						return ErrInvalid
					}
				}
			}
			stylesheet := false
			for _, a := range node.Attr {
				if a.Key == "rel" && strings.EqualFold(a.Val, "stylesheet") {
					stylesheet = true
				}
			}
			for i, a := range node.Attr {
				if a.Key == "srcset" || a.Key == "srcdoc" || a.Key == "action" || a.Key == "formaction" {
					return ErrInvalid
				}
				if a.Key != "src" && a.Key != "href" {
					continue
				}
				if strings.HasPrefix(a.Val, "#") {
					continue
				}
				var value string
				switch {
				case node.Data == "script" && a.Key == "src":
					value, err = dashboardReference(bundle, bundle.Entry, a.Val, "text/javascript")
				case node.Data == "link" && a.Key == "href" && stylesheet:
					value, err = dashboardReference(bundle, bundle.Entry, a.Val, "text/css")
				case node.Data == "img" && a.Key == "src" && strings.HasPrefix(strings.ToLower(a.Val), "data:image/"):
					continue
				default:
					return ErrInvalid
				}
				if err != nil {
					return err
				}
				node.Attr[i].Val = value
			}
		}
		for child := node.FirstChild; child != nil; child = child.NextSibling {
			if err := walk(child); err != nil {
				return err
			}
		}
		return nil
	}
	if err := walk(doc); err != nil {
		return "", err
	}
	var output bytes.Buffer
	if err := html.Render(&output, doc); err != nil {
		return "", err
	}
	return output.String(), nil
}

func validateDashboardMarkup(bundle *DashboardBundle) error {
	_, err := dashboardMarkup(bundle)
	return err
}

func (bundle *DashboardBundle) Markup() (string, error) { return dashboardMarkup(bundle) }

//go:embed dashboard-sdk.js
var dashboardSDK string

func (bundle *DashboardBundle) Document(nonce string) (string, error) {
	if len(nonce) != 32 || strings.Trim(nonce, "0123456789abcdef") != "" {
		return "", ErrInvalid
	}
	markup, err := bundle.Markup()
	if err != nil {
		return "", err
	}
	doc, err := html.Parse(strings.NewReader(markup))
	if err != nil {
		return "", err
	}
	var head *html.Node
	var locate func(*html.Node)
	locate = func(n *html.Node) {
		if n.Type == html.ElementNode && n.Data == "head" {
			head = n
			return
		}
		for c := n.FirstChild; c != nil; c = c.NextSibling {
			locate(c)
		}
	}
	locate(doc)
	if head == nil {
		return "", ErrInvalid
	}
	context, err := json.Marshal(map[string]any{"nonce": nonce, "digest": bundle.Digest, "metricIds": bundle.MetricIDs})
	if err != nil {
		return "", err
	}
	script := &html.Node{Type: html.ElementNode, Data: "script"}
	script.AppendChild(&html.Node{Type: html.TextNode, Data: "(" + dashboardSDK + ")(" + string(context) + ");"})
	head.InsertBefore(script, head.FirstChild)
	var out bytes.Buffer
	if err := html.Render(&out, doc); err != nil {
		return "", err
	}
	return out.String(), nil
}
