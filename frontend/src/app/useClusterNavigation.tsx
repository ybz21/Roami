import type { MenuProps } from 'antd'
import { NodeMark, nodeDotColor } from '../components/cluster/NodeMark'
import { hubReasonText, useHubHealth } from '../components/cluster/hub-health'
import { setCurrentNode, useClusterNodes, useCurrentNodeId } from '../components/cluster/node-url'
import { loadTabs } from '../components/terminal/term-tabs-store'
import { useI18n } from '../i18n'
import { CloudIcon } from '../icons'
import { NO_TERMS, setHashParams } from '../route-hash'

export function useClusterNavigation(noTabs: { readonly current: boolean }, go: (route: string) => void) {
  const { t } = useI18n()
  const clusterNodes = useClusterNodes()
  const curNodeId = useCurrentNodeId()
  const curNode = clusterNodes.find((n) => n.id === curNodeId) || null
  const hubHealth = useHubHealth()
  const switchNode = (id: string) => {
    const back = loadTabs(id)
    setCurrentNode(id)
    setHashParams({
      terms: noTabs.current ? NO_TERMS : back.terms.map(encodeURIComponent).join(','),
      active: noTabs.current || !back.active ? '' : encodeURIComponent(back.active),
    })
    location.reload()
  }

  const nodeItems: MenuProps['items'] = clusterNodes.length ? [
    ...clusterNodes.map((n) => ({
      key: 'node:' + n.id,
      label: (
        <span className={`tt-nodemenu${n.id === curNodeId ? ' on' : ''}`}>
          <NodeMark name={n.name} size="sm" current={n.id === curNodeId} offline={!n.online} />
          <span className="nm">{n.name}</span>
          <span className="lat">{n.online ? t('node.latencyMs', { ms: n.latencyMs }) : t('node.offline')}</span>
          <i className="dot" style={{ background: nodeDotColor(n) }} />
        </span>
      ),
      disabled: !n.online,
      onClick: () => switchNode(n.id),
    })),
    { type: 'divider' as const },
    {
      key: 'hub-page',
      label: (
        <span className={`tt-nodemenu hub${hubHealth.level === 'ok' ? '' : ' alarm'}`}>
          <span className="mk"><CloudIcon size={12} /></span>
          <span className="nm">{t('hub.title')}</span>
          <span className="lat">
            {hubHealth.level === 'ok'
              ? t('hub.onlineShort', { n: clusterNodes.filter((n) => n.online).length })
              : hubReasonText(hubHealth, t)}
          </span>
        </span>
      ),
      onClick: () => go('hub'),
    },
  ] : []

  return { clusterNodes, curNodeId, curNode, hubHealth, nodeItems }
}
