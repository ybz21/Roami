# Roami 蜂群 CLI

顶层入口是 `roami swarm`。`roami session swarm` 调用同一实现；不再依赖插件发现或隐藏别名，也不启动旧指挥。

```bash
roami help
roami swarm help
roami swarm member --help
roami swarm chat --help
```

帮助为只读，运行时尚未配置也能查看；帮助不会创建群、初始化存储或调用 tmux。Bash 补全同时支持两个入口，只列新命令。

## 与三个 Tab 对应

| Web | CLI |
| --- | --- |
| 协作 | status / members / member show / work |
| 群聊 | chat / say / post，chat --follow 实时跟随 |
| 看板 | board / collect，board --follow 实时跟随 |
| 创建与编排 | new / member add / plan / dependencies |
| 控制 | pause / resume / stop / archive |

Three.js 动画在 Web 协作页查看；CLI 提供同一真实状态、选择、通信和控制能力。

## 创建和查看

```bash
roami swarm new demo --key create-demo-1 --goal "实现功能并验收" --json
roami swarm ls
roami swarm ls --archived
roami swarm status <sw-id>
roami swarm show <sw-id>
roami swarm members <sw-id>
roami swarm work <sw-id> <成员名或工作项ID>
roami swarm board <sw-id> --json
roami swarm collect <sw-id>
```

new 默认复用节点 Main，也可加 `--main-conversation` 指定普通 Main 对话，`--dir` 指定工作目录。创建后由 Main 编排；需要手动补充时先从 status 读取计划修订。

work 同时读取原 Task 的完整结果、产物和执行记录。collect 只把真实 succeeded 工作列为已验收，执行器报告仍留在待审。

## 提交成员、依赖和整合

```bash
roami swarm member add <sw-id> api --executor codex \
  --goal "实现接口" --acceptance "接口测试通过" \
  --key member-api-1 --revision 1

roami swarm member add <sw-id> check --executor roami \
  --goal "整合并验收" --acceptance "端到端检查通过" \
  --depends-on api@1 --integration --key member-check-1 --revision 2

roami swarm dependencies <sw-id> check --depends-on 'api@2#ARTIFACT_ID' \
  --key deps-check-2 --revision 3
```

executor 支持 codex、claude、roami/native、opencode、pi。`--revision` 是计划修订，`成员@修订` 是上游 Task 修订，不能混用。依赖可重复指定。产物 pin 不允许空 ID。清空依赖必须显式 `--clear`；未知/活动执行先按既有停止证据门禁处理。

批量计划保留 `plan --file plan.json`，文件包含 commandKey、expectedRevision、items；`roami swarm plan --help` 给出 JSON 示例。计划、依赖、消息与 control 命令支持完整请求文件输入，`--file -` 支持 stdin；不能混用文件与其他业务参数。

## 群聊和原任务续改

```bash
roami swarm chat <sw-id> --limit 50
roami swarm chat <sw-id> --follow
roami swarm say <sw-id> "补充需求" --key note-1
roami swarm say <sw-id> "继续修改" --to api --task-revision 2 --key revise-api-2
```

发给 Main 的消息进入原对话；`--to` 解析所属成员的真实工作项，必须明确任务修订。未知投递重试保持相同 key、文本、接收人和修订，不能自动切到新修订。

专业执行器讨论使用 `post --file`，也可直接指定 `--task`、`--run`、`--task-revision`。作者由宿主校验；讨论不能推进验收状态，最终报告继续使用既有 Task 回报协议。

## 控制与实时读取

```bash
roami swarm pause <sw-id> --key pause-1 --revision 4
roami swarm resume <sw-id> --key resume-1 --revision 5
roami swarm stop <sw-id> --key stop-1 --revision 6
roami swarm archive <sw-id> --key archive-1 --revision 7
roami swarm status <sw-id> --follow --json
```

暂停仅冻结派发，停止走原 Task 取消，归档不关闭会话。冲突错误提示查看当前修订；旧停止请求重试保留原修订。

`--follow` 使用现有 SSE，保留 sequence、去重、退避重连，Ctrl-C 退出。不会另起轮询或模型循环。群聊仅包含服务最近消息/结果窗口，不能据重连声称补全全部历史。

JSON 读取使用 data envelope；board.data 包含五列，members/chat.data 为数组，collect.data 区分 verified 和 pending。实时输出为 NDJSON，含 id、kind、data；群聊先发 swarm.chat 历史窗口，再发 swarm.message 更新，看板发 swarm.board 快照。

## 验证

Go 契约及 race 测试覆盖帮助无副作用、两个入口、补全、参数校验、真实 task/run 绑定、修订重试、产物 pin、私有回传、SSE sequence/重放/重连/取消和待审不冒充验收。

隔离运行时实际验证了根入口/别名同群、直接成员与依赖写入、暂停幂等重试、停止/归档、可读视图及实时看板更新。测试群保持暂停，没有模型任务启动；真实模型 401 阻塞仍见[验收记录](acceptance.md)。
