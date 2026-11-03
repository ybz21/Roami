import React from 'react'
import { CycleKind } from './okr-execution-cycle'
import { DialogueScene, dialogueScenes } from './okr-dialogue-scenes'
import { swarmMessages, swarmProjection } from './okr-swarm-state'

export default function SwarmConversation({kind,scene,pending,onTask,onContinue,paused}:{kind:CycleKind;scene:DialogueScene;pending:{text:string;after:number}[];onTask:(id:string)=>void;onContinue?:()=>void;paused:boolean}) {
  const swarm = swarmProjection(kind,scene), messages = swarmMessages(kind,scene)
  return <div className="swarm-conversation" data-room-id={swarm.roomId} data-board-id={swarm.boardId}>
    <p className="meta">你与主责、执行、数据、反思智能体共享这个群。消息与看板任务相互引用；此处为离线回放。</p>
    {messages.map((message,index)=><React.Fragment key={message.id}><article className={`book-turn ${message.author === '你' ? 'user' : 'assistant'}`} data-author={message.author}><small>{message.author} · {message.date}</small><p>{message.text}</p>{message.facts && <details><summary>反思依据</summary><ul className="book-facts">{message.facts.map(fact=><li key={fact}>{fact}</li>)}</ul></details>}{message.taskId && <button type="button" className="tt-act" onClick={()=>onTask(message.taskId!)}>查看看板任务</button>}</article>{messages[index+1]?.sceneId !== message.sceneId && pending.filter(turn=>dialogueScenes[kind][turn.after]?.id===message.sceneId).map((turn,n)=><article className="book-turn user" key={n}><small>你 · 群聊补充</small><p>{turn.text}</p><small>输入已保留；离线演示尚无对应智能体回应。</small></article>)}</React.Fragment>)}
    {onContinue && <button type="button" className="button primary" disabled={paused} onClick={onContinue}>{scene.action ?? '回放下一次接力'}</button>}
  </div>
}
