import { useEffect, useRef, useState } from 'react'
import { useLayout } from '../../layout'
import { useI18n } from '../../i18n'
import type { StudioNode } from './swarm-protocol'
import type { createStudio } from './studio/studio-scene'

export default function SwarmStudio({ nodes, selected, onSelect, active = true, historical = false, compactHeader = false }: { nodes: StudioNode[]; selected: string; onSelect: (id: string) => void; active?: boolean; historical?: boolean; compactHeader?: boolean }) {
  const { t } = useI18n(), layout = useLayout()
  const host = useRef<HTMLDivElement>(null), labels = useRef<HTMLDivElement>(null), scene = useRef<ReturnType<typeof createStudio> | null>(null)
  const [failed, setFailed] = useState(false), [motion, setMotion] = useState(() => localStorage.getItem('roami.swarm.motion') !== 'off')
  const latest = useRef({ nodes, selected, onSelect, motion, historical, reducedMotion: layout.reducedMotion }); latest.current = { nodes, selected, onSelect, motion, historical, reducedMotion: layout.reducedMotion }
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    if (!active) return
    let disposed = false; setFailed(false)
    void import('./studio/studio-scene').then(({ createStudio }) => {
      if (disposed || !host.current || !labels.current) return
      try {
        scene.current = createStudio(host.current, labels.current, id => latest.current.onSelect(id), layout.coarse, () => { if (!disposed) setFailed(true) })
        scene.current.motion(latest.current.motion, latest.current.reducedMotion, latest.current.historical); scene.current.update(latest.current.nodes); scene.current.select(latest.current.selected)
      } catch { setFailed(true) }
    }).catch(() => { if (!disposed) setFailed(true) })
    return () => { disposed = true; scene.current?.dispose(); scene.current = null }
  }, [layout.coarse, retry, active])
  useEffect(() => { scene.current?.update(nodes) }, [nodes])
  useEffect(() => { scene.current?.select(selected) }, [selected])
  useEffect(() => { scene.current?.motion(motion, layout.reducedMotion, historical) }, [motion, layout.reducedMotion, historical])
  return <section className="swarm-studio" aria-label={t('swarm.studio.title')}>
    <header className="swarm-panel-head"><strong hidden={compactHeader}>{t(historical ? 'swarm.legacy.studio' : 'swarm.studio.title')}</strong><button type="button" className="tt-act" aria-pressed={motion} onClick={() => setMotion(value => { localStorage.setItem('roami.swarm.motion', value ? 'off' : 'on'); return !value })}>{t(motion ? 'swarm.studio.motionOn' : 'swarm.studio.motionOff')}</button></header>
    <div className="swarm-stage" ref={host}>
      <div className="swarm-labels" ref={labels} hidden={failed}>{nodes.slice(0, 24).map(node => <button type="button" key={node.id} data-studio-id={node.id} className="swarm-studio-label" aria-pressed={node.id === selected} onClick={() => onSelect(node.id)}>{node.name}</button>)}</div>
      {failed && <div className="swarm-scene-fallback" role="status"><p>{t('swarm.studio.unavailable')}</p><button type="button" className="tt-act" onClick={() => setRetry(value => value + 1)}>{t('agent.retry')}</button></div>}
    </div>
    {nodes.length > 24 && <p className="swarm-note">{t('swarm.studio.moreMembers')}</p>}
  </section>
}
