export type KrView = 'number' | 'milestones' | 'checklist'
export type GeneratedKr = { id: string; title: string; rationale: string; view: KrView; metricId?: string; target?: number; unit?: string; items?: string[]; horizon?: 'long'|'short'|'daily'; parentKrId?: string; period?: { start: string; end: string } }
export type GeneratedMetric = {
  id: string; krId: string; name: string; unit: string; rationale: string; connectorId: string;
  formula: { op: 'field'; field: string } | { op: 'difference'; field: string; baseline: number | null } | { op: 'ratio'; numerator: string; denominator: string };
}
export type BrowserConnector = {
  id: string; revision: number; name: string; method: 'browser'; origin: string; path: string;
  expectedAccountId: string; account: { selector: string; attribute: string };
  date: { selector: string; attribute: string };
  fields: { id: string; unit: string; selector: string }[];
}
export type GeneratedWidget = { id: string; type: 'metric' | 'trend' | 'records' | 'checks'; title: string; metricIds: string[]; krId?: string }
export type GeneratedPlan = {
  schemaVersion: 1; revision: number; statement: string; objective: string; rationale: string; cycleStart: string;
  assumptions: string[]; keyResults: GeneratedKr[]; metrics: GeneratedMetric[];
  connectors: BrowserConnector[]; widgets: GeneratedWidget[]; dailyAction: string;
}
export type BrowserObservation = {
  connectorId: string; connectorRevision: number; accountId: string; date: string; capturedAt: string;
  sourceUrl: string; evidenceKind: 'replay' | 'browser-fixture';
  values: Record<string, { value: number; unit: string }>;
}
export function formulaFields(metric: GeneratedMetric): string[] {
  return metric.formula.op === 'ratio' ? [metric.formula.numerator,metric.formula.denominator] : [metric.formula.field]
}
const plain = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const text = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0 && value.length <= 4000
function validDate(value: unknown): value is string { return text(value) && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0,10) === value }
function fail(message: string): never { throw new Error(message) }
function list(value: unknown, label: string): unknown[] { if (!Array.isArray(value) || value.length > 40) fail(`${label}应为不超过 40 项的数组。`); return value }
function strings(value: unknown, label: string): string[] { const result = list(value,label); if (!result.every(text)) fail(`${label}中有空值。`); return result as string[] }
function entries(value: unknown, label: string): Record<string, unknown>[] {
  const result = list(value,label)
  if (!result.every(plain)) fail(`${label}格式不正确。`)
  const ids = result.map(item => item.id)
  if (!ids.every(id => text(id) && /^[a-zA-Z][a-zA-Z0-9_-]{0,63}$/.test(id)) || new Set(ids).size !== ids.length) fail(`${label}需要唯一的英文 ID。`)
  return result as Record<string, unknown>[]
}
export function parsePlan(input: string): GeneratedPlan {
  if (input.length > 100000) fail('方案过大，请保留本次目标需要的内容。')
  const p: unknown = JSON.parse(input)
  if (!plain(p) || p.schemaVersion !== 1 || !Number.isInteger(p.revision) || Number(p.revision) < 1 || ![p.statement,p.objective,p.rationale,p.dailyAction].every(text)) fail('方案缺少目标、修订或说明。')
  if (!text(p.cycleStart) || !/^\d{4}-\d{2}-\d{2}$/.test(p.cycleStart) || !Number.isFinite(Date.parse(p.cycleStart)) || new Date(p.cycleStart).toISOString().slice(0,10) !== p.cycleStart) fail('请提供有效周期开始日期。')
  strings(p.assumptions,'假设')
  const krs = entries(p.keyResults,'KR'), metrics = entries(p.metrics,'指标'), connectors = entries(p.connectors,'连接器'), widgets = entries(p.widgets,'组件')
  if (!krs.length || !metrics.length || !widgets.length) fail('至少需要一条 KR、一个指标和一个组件。')
  for (const c of connectors) {
    if (c.method !== 'browser' || ![c.name,c.origin,c.path,c.expectedAccountId].every(text) || !Number.isInteger(c.revision) || Number(c.revision) < 1) fail('连接器描述不完整。')
    const url = new URL(c.origin as string)
    if (!['https:','http:'].includes(url.protocol) || url.origin !== c.origin || !(c.path as string).startsWith('/')) fail('连接器需要明确的 HTTP 来源和路径。')
    for (const part of [c.account,c.date]) if (!plain(part) || !text(part.selector) || !text(part.attribute)) fail('连接器缺少身份或日期定位方式。')
    const fields = entries(c.fields,'来源字段')
    if (!fields.length || fields.some(f => !text(f.unit) || !text(f.selector))) fail('来源字段需要单位和选择器。')
  }
  for (const m of metrics) {
    if (![m.name,m.unit,m.rationale].every(text) || !krs.some(k => k.id === m.krId) || !plain(m.formula)) fail('指标缺少 KR、口径或理由。')
    const f = m.formula
    if (!['field','difference','ratio'].includes(String(f.op)) || (f.op === 'ratio' ? !text(f.numerator) || !text(f.denominator) : !text(f.field)) || f.op === 'difference' && f.baseline !== null && (typeof f.baseline !== 'number' || !Number.isFinite(f.baseline))) fail('不支持该计算口径。')
    if (f.op === 'difference' && f.baseline !== null) fail('净增起点须由有效观测建立，模型方案不能直接填写。')
    const source = connectors.find(c => c.id === m.connectorId)
    if (!source || formulaFields(m as unknown as GeneratedMetric).some(id => !(source.fields as Record<string,unknown>[]).some(field => field.id === id))) fail('指标引用了不存在的来源字段。')
    const fields = source.fields as Record<string,unknown>[]
    if (f.op === 'ratio' ? m.unit !== '%' || fields.find(x => x.id === f.numerator)?.unit !== fields.find(x => x.id === f.denominator)?.unit : fields.find(x => x.id === f.field)?.unit !== m.unit) fail('指标与来源字段单位不兼容。')
  }
  for (const k of krs) {
    if (![k.title,k.rationale].every(text) || !['number','milestones','checklist'].includes(String(k.view))) fail('KR 缺少内容或使用了未知展现形式。')
    if (k.view === 'number') { if (typeof k.target !== 'number' || !Number.isFinite(k.target) || !text(k.unit) || !metrics.some(m => m.id === k.metricId && m.krId === k.id && m.unit === k.unit)) fail('数值 KR 需要同单位的主指标与目标。') }
    else if (!strings(k.items,'验收条目').length) fail('阶段或验收 KR 需要具体条目。')
    if (k.horizon !== undefined && !['long','short','daily'].includes(String(k.horizon))) fail('未知的 KR 时间层次。')
    if (k.period !== undefined && (!plain(k.period) || !validDate(k.period.start) || !validDate(k.period.end) || k.period.start > k.period.end)) fail('KR 周期不正确。')
    const seen = new Set([k.id]); let parentId = k.parentKrId
    while (parentId !== undefined) {
      const parent = krs.find(item => item.id === parentId)
      if (!parent || seen.has(parentId)) fail('KR 的父级不存在或形成循环。')
      seen.add(parentId);parentId = parent.parentKrId
    }
    const parent = krs.find(item => item.id === k.parentKrId)
    if (parent && plain(parent.period) && plain(k.period) && ((k.period.start as string) < (parent.period.start as string) || (k.period.end as string) > (parent.period.end as string))) fail('短周期不能越过关联父 KR 的周期。')
  }
  for (const w of widgets) {
    if (!text(w.title) || !['metric','trend','records','checks'].includes(String(w.type))) fail('看板包含未知组件。')
    const ids = strings(w.metricIds,'组件指标')
    if (ids.some(id => !metrics.some(m => m.id === id)) || w.type !== 'checks' && !ids.length || w.type === 'metric' && ids.length !== 1) fail('组件的指标引用不正确。')
    if (w.type === 'checks' && !krs.some(k => k.id === w.krId && k.view !== 'number')) fail('验收组件需要对应的阶段或清单 KR。')
  }
  return p as unknown as GeneratedPlan
}
export function validateObservation(input: unknown, plan: GeneratedPlan): BrowserObservation {
  if (!plain(input)) fail('读取结果应为 JSON 对象。')
  const c = plan.connectors.find(c => c.id === input.connectorId)
  if (!c || c.revision !== input.connectorRevision || c.expectedAccountId !== input.accountId) fail('连接器版本或账号不符，请重新取样。')
  if (!text(input.date) || !/^\d{4}-\d{2}-\d{2}$/.test(input.date) || !Number.isFinite(Date.parse(input.date)) || new Date(input.date).toISOString().slice(0,10) !== input.date || !text(input.capturedAt) || !Number.isFinite(Date.parse(input.capturedAt))) fail('缺少有效的观测日期与采集时间。')
  if (!['replay','browser-fixture'].includes(String(input.evidenceKind)) || !plain(input.values) || !text(input.sourceUrl)) fail('读取结果缺少来源或字段。')
  const url = new URL(input.sourceUrl)
  if (url.origin !== c.origin || url.pathname !== c.path) fail('样本网页与连接器约定不符。')
  const required = [...new Set(plan.metrics.filter(m => m.connectorId === c.id).flatMap(formulaFields))]
  for (const field of required) {
    const found = input.values[field], contract = c.fields.find(f => f.id === field)!
    if (!plain(found) || typeof found.value !== 'number' || !Number.isFinite(found.value) || found.value < 0 || found.unit !== contract.unit) fail(`字段 ${field} 缺失或单位不符；保留原记录。`)
  }
  for (const m of plan.metrics.filter(m => m.connectorId === c.id && m.formula.op === 'ratio')) {
    if (m.formula.op === 'ratio' && (input.values[m.formula.numerator] as {value:number}).value > (input.values[m.formula.denominator] as {value:number}).value) fail('分子大于分母，请核对统计口径。')
  }
  return input as unknown as BrowserObservation
}
export function measuredValue(metric: GeneratedMetric, observations: BrowserObservation[], date: string): number | null {
  const row = observations.find(row => row.connectorId === metric.connectorId && row.date === date)
  if (!row) return null
  const f = metric.formula, value = (key: string) => row.values[key]?.value ?? null
  if (f.op === 'field') return value(f.field)
  if (f.op === 'difference') { const current = value(f.field); return current === null || f.baseline === null ? null : current - f.baseline }
  const numerator = value(f.numerator), denominator = value(f.denominator)
  return numerator === null || denominator === null || denominator === 0 ? null : numerator / denominator * 100
}
