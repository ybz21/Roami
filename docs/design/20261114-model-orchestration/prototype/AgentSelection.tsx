import { useState } from 'react'
import { Alert, Button, Radio } from 'antd'
import ModelSelectionFields, { type ModelChoice } from '../../../../frontend/src/components/capabilities/ModelSelectionFields'
import { previewSelection } from './fixture'

type Mode = 'session' | 'delegate'
const initialChoice: ModelChoice = { model: 'auto', freeOnly: false }

export function AgentSelection() {
  const [mode, setMode] = useState<Mode>('session')
  const [drafts, setDrafts] = useState({ session:initialChoice, delegate:initialChoice })
  const [receipt, setReceipt] = useState<{ note: string; ready: boolean }>()
  const value = drafts[mode]
  return <section className="tt-model-hub-scroll prototype-agent">
    <header className="tt-pagehead"><h2>会话与委派选模</h2></header>
    <div className="agent-settings-form">
      <Radio.Group value={mode} onChange={event => { setMode(event.target.value); setReceipt(undefined) }}>
        <Radio.Button value="session">创建会话</Radio.Button>
        <Radio.Button value="delegate">委派任务</Radio.Button>
      </Radio.Group>
      <ModelSelectionFields value={value} onChange={next => { setDrafts(old => ({ ...old, [mode]: next })); setReceipt(undefined) }} />
      <Button type="primary" onClick={() => setReceipt(previewSelection(value))}>预览调度结果</Button>
      {receipt && <Alert type={receipt.ready ? 'success' : 'warning'} showIcon message={receipt.note} />}
    </div>
  </section>
}
