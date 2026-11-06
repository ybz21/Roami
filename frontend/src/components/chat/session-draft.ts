import { currentNodeId } from '../cluster/node-url'

export function sessionDraftKey(name: string) {
  return 'roami.session.draft:' + (currentNodeId() || '') + ':' + name
}
