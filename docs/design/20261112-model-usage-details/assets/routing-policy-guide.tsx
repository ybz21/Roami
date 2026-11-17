import React from 'react'
import { useI18n } from '../../../../frontend/src/i18n'
import { strategyCopy, type RoutingStrategy } from './routing-strategies'
export function RoutingPolicyGuide({strategy}:{strategy:RoutingStrategy}) {
 const {locale}=useI18n(),zh=locale==='zh-CN',value=strategyCopy[locale][strategy]
 return <div className="routing-policy-guide"><p>{value.summary}</p><details><summary>{zh?'策略细则':'Policy details'}</summary><p>{value.detail}</p>{strategy==='cheap'&&<><p>{zh?'按本次需求的分时规则设计，以下为示例计价条件。':'Time-of-day examples follow the requested routing rules.'}</p><ul><li>{zh?'DeepSeek 官方 API、Command Code、OpenCode Go 的 DeepSeek：工作日 UTC 01:00–04:00、06:00–10:00 为 2 倍。':'DeepSeek via the official API, Command Code or OpenCode Go: 2× on weekdays at UTC 01:00–04:00 and 06:00–10:00.'}</li><li>{zh?'Ollama Cloud 的 DeepSeek V4.1 Flash / V4 Pro：工作日 UTC 12:00–18:00 为高峰价，其他时间半价。':'Ollama Cloud DeepSeek V4.1 Flash / V4 Pro: peak on weekdays at UTC 12:00–18:00; half price otherwise.'}</li></ul><p>{zh?'实际计价规则后续以源配置为准。':'Actual pricing will follow source configuration.'}</p></>}{strategy==='weight'&&<p>{zh?'权重分给模型成员；成员内部按提供方自己的策略选账号或 Key。嵌套路由组只占一个成员权重。':'Weights belong to model members. Providers choose their own account/key; a nested group has one member weight.'}</p>}</details></div>
}
