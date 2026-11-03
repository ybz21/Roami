package interactive

import (
	"fmt"
	"os"
	"strconv"
	"time"

	"github.com/ybz21/Roami/internal/terminalui"
)

func (m *menu) swarmMenu() {
	_ = m.run([]string{"swarm", "ls"})
	fmt.Println("  n) 新建蜂群   s) 查看状态   回车返回")
	action, _ := ui.ReadLine("  选择: ")
	switch action {
	case "n":
		name, _ := ui.ReadLine("  蜂群名称: ")
		goal, _ := ui.ReadLine("  目标与验收标准: ")
		if name != "" && goal != "" {
			_ = m.run([]string{"swarm", "new", name, "--goal", goal, "--key", "interactive:" + strconv.FormatInt(time.Now().UnixNano(), 10)})
		}
	case "s":
		id, _ := ui.ReadLine("  蜂群 ID: ")
		if id != "" {
			if err := m.run([]string{"swarm", "status", id}); err != nil {
				ui.Err(os.Stdout, "%s", err)
			}
		}
	}
	m.pause()
}
