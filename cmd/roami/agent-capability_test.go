package main

import "testing"

func TestAgentCapabilityListsCategoriesAndRejectsRemovedSearch(t *testing.T) {
	if code := runAgentCapability([]string{"list", "--help"}); code != 0 {
		t.Fatalf("list help exit: %d", code)
	}
	if code := runAgentCapability([]string{"search", "--query", "browser"}); code != 2 {
		t.Fatalf("removed search entry remained callable: %d", code)
	}
}
