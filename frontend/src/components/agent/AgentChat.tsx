import AgentConversation, { type HomeConversationProps } from './AgentConversation'

export { agentFailure } from './agent-request-failure'

export default function AgentChat(props: HomeConversationProps) {
  return <AgentConversation {...props} />
}
