// 对话内容块 —— 遵循 Anthropic 标准块类型；Codex 转录也归一到同一形状。
export interface Block {
  kind: string          // text | thinking | tool_use | tool_result
  text?: string
  name?: string         // tool_use 工具名
  input?: string        // tool_use 入参(JSON 字符串)
  id?: string           // tool_use 的 id
  toolUseId?: string    // tool_result 对应的 tool_use id
  isError?: boolean
}
export interface Msg { role: string; blocks: Block[]; ts?: string; id?: string; final?: boolean }

export type NativeMainTurn = { id: string; startedMs?: number }
