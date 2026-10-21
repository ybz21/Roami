package main

func runADB(args []string) int {
	if len(args) == 0 {
		args = []string{"help"}
	}
	return forward("adb", args)
}
