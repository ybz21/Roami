package agent

// Descriptor is the UI and discovery contract for a registered harness.
type Descriptor struct {
	Kind         string `json:"kind"`
	DisplayName  string `json:"displayName"`
	PromptFlag   string `json:"promptFlag,omitempty"`
	SetupCommand string `json:"setupCommand,omitempty"`
	Command      string `json:"command"`
	Interactive  bool   `json:"interactive"`
	Models       bool   `json:"models"`
	CanInstall   bool   `json:"canInstall"`
}

type Package struct {
	Name          string
	Tag           string
	IgnoreScripts bool
}

func Describe(a Agent) Descriptor {
	d := Descriptor{Kind: a.Kind(), DisplayName: a.DisplayName(), Command: a.Bin(), Interactive: true}
	if custom, ok := a.(interface{ Descriptor() Descriptor }); ok {
		d = custom.Descriptor()
		d.Kind, d.DisplayName = a.Kind(), a.DisplayName()
	}
	if _, ok := a.(interface{ ModelConfiguration() }); ok {
		d.Models = true
	}
	if flag, ok := a.(interface{ PromptFlag() string }); ok {
		d.PromptFlag = flag.PromptFlag()
	}
	_, d.CanInstall = InstallPackage(a.Kind())
	return d
}

func Descriptors() []Descriptor {
	out := make([]Descriptor, 0)
	for _, kind := range Kinds() {
		out = append(out, Describe(Get(kind)))
	}
	return out
}

func InstallPackage(kind string) (Package, bool) {
	a := Get(kind)
	if source, ok := a.(interface{ InstallPackage() Package }); ok {
		pkg := source.InstallPackage()
		return pkg, pkg.Name != ""
	}
	return Package{}, false
}

func (p Package) Spec() string {
	if p.Tag != "" {
		return p.Name + "@" + p.Tag
	}
	return p.Name
}
