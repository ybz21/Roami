package help

import (
	"bytes"
	"errors"
	"io"
	"strings"
	"testing"
)

func TestPageReadableWithoutANSI(t *testing.T) {
	var out bytes.Buffer
	err := (Page{Command: "roami demo", Summary: "命令演示", Usage: []string{"roami demo <命令>"}, Sections: []Section{{"命令", []Entry{{"ls", "列出"}, {"show", "查看"}, {"a-command-with-a-long-argument NAME", "说明放在下一行"}}}}, Examples: []Entry{{"roami demo ls", ""}}, More: "roami demo -h"}).Render(&out)
	if err != nil {
		t.Fatal(err)
	}
	want := "roami demo — 命令演示\n\n用法\n  roami demo <命令>\n\n命令\n  ls    列出\n  show  查看\n  a-command-with-a-long-argument NAME\n    说明放在下一行\n\n示例\n  roami demo ls\n\n进一步帮助：roami demo -h\n"
	if out.String() != want {
		t.Fatalf("unexpected layout:\n%s", out.String())
	}
}

type failingWriter struct{}

func (failingWriter) Write([]byte) (int, error) { return 0, io.ErrClosedPipe }
func TestPageReportsWriteFailure(t *testing.T) {
	if err := (Page{}).Render(failingWriter{}); !errors.Is(err, io.ErrClosedPipe) {
		t.Fatal(err)
	}
}

func TestForkHelpExplainsHowToUseIt(t *testing.T) {
	var out bytes.Buffer
	if !Command("fork", &out) {
		t.Fatal("fork help missing")
	}
	for _, want := range []string{"[PARENT] NAME", "省略时使用当前会话", "--dir PATH", "--detach", "--json", "roami session fork review --detach", "roami session fork PARENT_ID review --dir . --detach --json", "不复制 Agent 对话"} {
		if !strings.Contains(out.String(), want) {
			t.Fatalf("missing %q:\n%s", want, out.String())
		}
	}
}
