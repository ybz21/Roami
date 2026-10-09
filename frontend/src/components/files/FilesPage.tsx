import { useEffect, useState } from 'react'
import FileBrowser from './FileBrowser'
import FileWorkspace from './FileWorkspace'
import MobileSubPage from '../MobileSubPage'
import { api } from '../../api'
import { FileView } from './fileview'
import { useI18n } from '../../i18n'
import { INTENT_EVENT, OPEN_FILE_INTENT, takeIntentData } from '../../intents'
import { useLayout } from '../../layout'
import { pathBasename, pathDirname } from '../../path-name'
import { usePreferences } from '../../preferences'
import { agentName, type AgentKind } from '../../agent-kind'
import { agentLaunch } from '../../agent-command'
import { App as AntApp } from 'antd'

export default function FilesPage({ openTerm }: { openTerm: (name: string) => void }) {
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const [prefs] = usePreferences()
  // 手机(窄屏)两级导航：一级整页文件列表，点文件后详情以全屏二级页(MobileSubPage)展开；
  // 桌面仍是 FileWorkspace(文件树 dock + 多 tab 编辑)。
  const { phone: isMobile } = useLayout()
  const [mobileFile, setMobileFile] = useState<string | null>(null)
  // 搜到文件 → 切到本页 → 打开它。桌面那条路径在 FileWorkspace 里（开成标签页），
  // 手机这里是二级全屏页，所以各接各的。
  useEffect(() => {
    if (!isMobile) return
    const on = () => {
      const data = takeIntentData<{ path?: string }>(OPEN_FILE_INTENT)
      const p = data && data !== true ? data.path : ''
      if (p) setMobileFile(p)
    }
    on()
    window.addEventListener(INTENT_EVENT, on)
    return () => window.removeEventListener(INTENT_EVENT, on)
  }, [isMobile])
  const openAgent = async (kind: AgentKind, file: string) => {
    const base = pathBasename(file).replace(/[^a-zA-Z0-9_.-]+/g, '-').slice(0, 28) || 'file'
    const name = `${kind}-${base}-${Date.now().toString(36).slice(-5)}`
    const dir = pathDirname(file)
    const cmd = agentLaunch(kind, prefs, t('file.agentPrompt', { path: file }))
    try {
      const res = await api('POST', '/sessions', { name, dir })
      const actual = res.name || name
      await api('POST', '/tasks/_/send', { sess: actual, msg: cmd })
      message.success(t('file.openedInAgent', { agent: kind === 'claude' ? 'Claude Code' : agentName(kind) }))
      openTerm(actual)
    } catch (e: any) {
      message.error(t('file.openFailed', { message: e.message }))
    }
  }
  if (isMobile) {
    return (
      <div style={{ height: '100%', minHeight: 0, display: 'flex' }}>
        <FileBrowser dir="" accent="var(--accent)" layout="dock" onOpenFile={setMobileFile} onOpenAgent={openAgent} />
        {mobileFile && (
          <MobileSubPage onBack={() => setMobileFile(null)}>
            <FileView path={mobileFile} accent="var(--accent)" inline onBack={() => setMobileFile(null)}
              onClose={() => setMobileFile(null)} onOpenPath={setMobileFile} onOpenAgent={openAgent} />
          </MobileSubPage>
        )}
      </div>
    )
  }
  return (
    <div style={{ height: '100%', minHeight: 0, display: 'flex' }}>
      <FileWorkspace dir="" accent="var(--accent)" onOpenAgent={openAgent} />
    </div>
  )
}
