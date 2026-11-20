import { useState } from 'react'
import { Button } from 'antd'

export function SpeechPreview() {
  const [phase, setPhase] = useState<'ready' | 'recording' | 'result'>('ready')
  return <section className="prototype-speech" aria-labelledby="speech-preview-heading">
    <header className="tt-pagehead"><h2 id="speech-preview-heading">试转写</h2></header>
    <p className="agent-settings-hint">使用演示样本。</p>
    {phase === 'recording' ? <div className="prototype-speech-actions">
      <Button type="primary" onClick={() => setPhase('result')}>停止并转写</Button>
      <Button onClick={() => setPhase('ready')}>取消</Button>
    </div> : <Button onClick={() => setPhase('recording')}>{phase === 'result' ? '再试一次' : '开始试录'}</Button>}
    <div className="prototype-speech-result" role="status">
      {phase === 'recording' && '正在试录'}
      {phase === 'result' && '演示识别结果：明天下午把模型用量发给我。'}
    </div>
  </section>
}
