import { useEffect, useRef } from 'react'
import audit from '../audit.html'
import monitor from '../monitor.html'
import '../assets/observation.js'
import '../assets/observation.css'

type View = 'monitor' | 'audit'
type DestinationRequest = { entry: string; attempts: { source: string }[] }
type Navigation = {
  query: () => string
  href: (page: View, query: string) => string
  destination: (page: 'usage' | 'sources' | 'aggregation', row: DestinationRequest) => string
  isCurrent: () => boolean
  pools: Record<string, string>
  sources: Record<string, { name: string; model: string }>
}
type ObservationWindow = typeof globalThis & {
  mountRoamiObservation: (host: HTMLElement, navigation: Navigation) => () => void
}
const extractContent = (html: string) => {
  const main = html.match(/<main\b[^>]*>([\s\S]*?)<\/main>/)
  if (!main) throw new Error('Observation page has no main content')
  return main[1]
}
const fragments = { monitor: extractContent(monitor), audit: extractContent(audit) }

export function ObservationPage({ view }: { view: View }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const noLongerMounted = (globalThis as ObservationWindow).mountRoamiObservation(ref.current!, {
      query: () => location.hash.split('?')[1] || '',
      href: (page, query) => '#/' + page + (query ? '?' + query : ''),
      destination: (page, row) => {
        if (page === 'usage') return '#/usage'
        if (page === 'aggregation') return '#/aggregate/' + (row.entry === 'okr' ? 'vision' : 'free')
        const source = row.attempts.at(-1)?.source
        return source ? '#/catalog/source/' + (source === 'lan' ? 'demo-api' : encodeURIComponent(source)) : '#/catalog'
      },
      isCurrent: () => location.hash.split('?')[0] === '#/' + view,
      pools: { coding: 'free', okr: 'Vision fallback' },
      sources: {
        workbuddy: { name: 'WorkBuddy · Demo', model: 'hy4-flash' },
        openrouter: { name: 'OpenRouter · Free', model: 'ernie-flash:free' },
        lan: { name: 'Demo API', model: 'vision-pro' },
      },
    })
    return noLongerMounted
  }, [view])
  return <div ref={ref} className="trace-layout embedded-observation" data-view={view}>
    <div id="trace-content" className="trace-content" dangerouslySetInnerHTML={{ __html: fragments[view] }} />
  </div>
}
