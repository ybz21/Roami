import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Popconfirm, Space, Spin, Typography, message } from 'antd'
import { AgentLogo } from '../../icons'
import { agentName, isAgentKind } from '../../agent-kind'
import { discoverAgents, installAgent, type RegisteredAgent } from '../../agent-registry'

type T = (key: string, vars?: Record<string, string | number>) => string

export default function AgentDiscoveryPanel({ enabled, t }: { enabled: boolean; t: T }) {
  const [agents, setAgents] = useState<RegisteredAgent[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const reload = useCallback(async () => {
    if (!enabled) { setLoading(false); return }
    try { setAgents(await discoverAgents()) }
    catch (error: any) { message.error(error.message) }
    finally { setLoading(false) }
  }, [enabled])
  useEffect(() => { reload() }, [reload])

  const install = async (kind: string) => {
    setBusy(kind)
    try {
      await installAgent(kind)
      message.success(t('agentDiscovery.installed'))
      await reload()
    } catch (error: any) { message.error(error.message) }
    finally { setBusy('') }
  }

  if (!enabled) return <Alert type="info" message={t('agentDiscovery.enable')} />
  if (loading) return <Spin />
  return <Space direction="vertical" style={{ width: '100%' }} size="middle">
    <Typography.Text type="secondary">{t('agentDiscovery.intro')}</Typography.Text>
    <Button className="tt-agent-discovery-action" onClick={reload}>{t('agentDiscovery.refresh')}</Button>
    {agents.map((agent) => {
      const q = agent.quota
      const name = isAgentKind(agent.kind) ? agentName(agent.kind) : agent.kind
      return <Card key={agent.kind} size="small" title={<Space size={8}>
        {isAgentKind(agent.kind) && <AgentLogo kind={agent.kind} size={16} />}{name}
      </Space>} extra={agent.installed ? null : <Popconfirm
        title={t('agentDiscovery.installConfirm', { name })} onConfirm={() => install(agent.kind)}
        okText={t('agentDiscovery.install')} cancelText={t('cron.cancel')}>
        <Button className="tt-agent-discovery-action" loading={busy === agent.kind}>{t('agentDiscovery.install')}</Button>
      </Popconfirm>}>
        <Space direction="vertical" size={2}>
          <Typography.Text>{t(agent.installed ? 'agentDiscovery.detected' : 'agentDiscovery.missing')}</Typography.Text>
          {q.state === 'available' && q.windows?.length ? q.windows.map((window) =>
            <Typography.Text key={window.windowMinutes} type="secondary">
              {t('agentDiscovery.remaining', { percent: Math.round(window.remainingPercent), minutes: window.windowMinutes })}
            </Typography.Text>) : <Typography.Text type="secondary">
            {q.state === 'available' && q.remainingPercent !== undefined
              ? t('agentDiscovery.remaining', { percent: Math.round(q.remainingPercent), minutes: q.windowMinutes || 0 })
              : t('agentDiscovery.quotaUnknown')}
          </Typography.Text>}
          {q.observedAt && <Typography.Text type="secondary">{t('agentDiscovery.observed', { time: new Date(q.observedAt).toLocaleString() })}</Typography.Text>}
        </Space>
      </Card>
    })}
  </Space>
}
