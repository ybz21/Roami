import type { MenuProps } from 'antd'
import { NodeMark, nodeDotColor } from '../components/cluster/NodeMark'
import { hubReasonText, useHubHealth } from '../components/cluster/hub-health'
import { setCurrentNode, useClusterNodes, useCurrentNodeId } from '../components/cluster/node-url'
import { useI18n } from '../i18n'
import { CloudIcon } from '../icons'
import { getHashParams, setHashParams } from '../route-hash'

export function useClusterNavigation(go: (route: string) => void) {
  const { t } = useI18n()
  const clusterNodes = useClusterNodes()
  const curNodeId = useCurrentNodeId()
  const curNode = clusterNodes.find((n) => n.id === curNodeId) || null
  const hubHealth = useHubHealth()
  const switchNode = (id: string) => {
    setCurrentNode(id)
    const params = Object.fromEntries(getHashParams())
    delete params.terms; delete params.active
    params.node = id
    setHashParams(params)
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
