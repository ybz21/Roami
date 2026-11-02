// 一行设置：名字 → 说明 → 控件，顺序固定。
//
// 紧凑控件（开关 / 分段 / 下拉 / 单行文本）收在标题行右端，不落到说明下面：
// 设置页一页不滚，行高就是预算——VSCode 把控件摆在说明下面，那是一页可以滚的排法。
// 手指档标题行会换行，控件自然掉到下一行，不挤成一条。
import { useEffect, useState } from 'react'
import { Input, Segmented, Select, Switch } from 'antd'
import type { SettingItem } from './registry'
import { useI18n } from '../../i18n'

/** 高亮搜索命中的词。命中是子串匹配，所以这里也按子串切，不做分词。 */
function Hi({ text, q }: { text: string; q: string }) {
  if (!q) return <>{text}</>
  const i = text.toLowerCase().indexOf(q)
  if (i < 0) return <>{text}</>
  return <>{text.slice(0, i)}<mark className="tt-set-hit">{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>
}

/** 文本控件：失焦提交，不给「保存」按钮——一页里五个保存按钮是五次犹豫 */
export function TextControl({ get, set, placeholder, label }: { get: () => string; set: (v: string) => void; placeholder?: string; label?: string }) {
  const stored = get()
  const [draft, setDraft] = useState(stored)
  useEffect(() => { setDraft(stored) }, [stored])
  return (
    <Input
      aria-label={label} value={draft} placeholder={placeholder} style={{ maxWidth: 300 }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => { if (draft !== stored) set(draft) }}
      onPressEnter={(e) => (e.target as HTMLInputElement).blur()}
    />
  )
}

export function SettingRow({ item, q = '' }: { item: SettingItem; q?: string }) {
  const { t } = useI18n()
  const c = item.control
  // 整页只有这一块时页头已经写了标题，行头再写一遍就是同一句话说两次。
  // 搜索结果里也不画（SettingsPage 已经先滤掉）：那儿只留一行「页名 + 打开这一页」。
  if (item.bare && c.kind === 'custom') return q ? null : <div className="tt-set-bare">{c.node}</div>
  const inline = c.kind !== 'custom'
  const badge = item.badge === 'exp' ? t('settings.p2pExperimental') : item.badge === 'restart' ? t('set.restartBadge') : ''

  let control: React.ReactNode = null
  if (c.kind === 'switch') control = <Switch checked={c.get()} onChange={c.set} aria-label={item.label} />
  else if (c.kind === 'segment') control = <Segmented value={c.get()} onChange={(v) => c.set(String(v))} options={c.options} />
  else if (c.kind === 'select') control = <Select value={c.get()} onChange={c.set} options={c.options} style={{ width: 160 }} aria-label={item.label} />
  else if (c.kind === 'text') control = <TextControl label={item.label} get={c.get} set={c.set} placeholder={c.placeholder} />

  return (
    <div className="tt-set-row">
      <div className="t">
        <span className="name"><Hi text={item.label} q={q} /></span>
        {item.scope && <span className="tt-set-scope">{t('set.scope' + ({ mine: 'Mine', node: 'Node', cluster: 'Cluster', browser: 'Browser' }[item.scope]))}</span>}
        {badge && <span className={`tt-set-badge${item.badge === 'restart' ? ' warn' : ''}`}>{badge}</span>}
        {inline && <><span className="grow" />{control}</>}
      </div>
      {item.desc && <p className="d"><Hi text={item.desc} q={q} /></p>}
      {c.kind === 'custom' && <div className="ctl">{c.node}</div>}
    </div>
  )
}
