package modelgateway

import (
	"regexp"
	"strconv"
	"strings"
)

const maxSourceKeyLength = 160

var sourceKeyPattern = regexp.MustCompile(`^[A-Za-z0-9-]{1,160}$`)

// Reserve saved keys before assigning keys to legacy and automatically imported sources.
func assignSourceKeys(sources []ModelSource) bool {
	used := make(map[string]bool, len(sources))
	for _, source := range sources {
		if source.SourceKey != nil && sourceKeyPattern.MatchString(*source.SourceKey) {
			used[*source.SourceKey] = true
		}
	}
	changed := false
	for i := range sources {
		source := &sources[i]
		base := source.ID
		if source.SourceKey != nil {
			if sourceKeyPattern.MatchString(*source.SourceKey) {
				continue
			}
			base = *source.SourceKey
		}
		base = strings.Join(strings.FieldsFunc(base, func(r rune) bool {
			return !(r >= 'A' && r <= 'Z' || r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '-')
		}), "-")
		if base == "" {
			base = "source"
		}
		base = base[:min(len(base), maxSourceKeyLength)]
		key := base
		for index := 2; used[key]; index++ {
			suffix := "-" + strconv.Itoa(index)
			key = base[:min(len(base), maxSourceKeyLength-len(suffix))] + suffix
		}
		used[key] = true
		source.SourceKey = &key
		changed = true
	}
	return changed
}

func newSourcesHaveKeys(next, previous []ModelSource) bool {
	saved := make(map[string]bool, len(previous))
	for _, source := range previous {
		saved[source.ID] = true
	}
	for _, source := range next {
		if source.SourceKey == nil && !saved[source.ID] {
			return false
		}
	}
	return true
}
