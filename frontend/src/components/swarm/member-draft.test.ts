// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from 'vitest'
import { transferMemberDraft } from './swarm-member-draft'
import type { SwarmTeamMember } from './swarm-members'
vi.mock('../cluster/node-url', () => ({ nodeApi: (path: string) => path, currentNodeId: () => null }))
const member = { id:'role', work:{ id:'work' } } as SwarmTeamMember
const oldKey = 'roami.swarm.draft:/agent/swarms/swarm', target='roami.session.draft::original'
beforeEach(() => localStorage.clear())
it('moves an exact legacy work draft once while preserving the original and an existing session draft', () => {
  const raw=JSON.stringify({ scope:'work', draft:'Original message' }); localStorage.setItem(oldKey,raw)
  transferMemberDraft('swarm',member,'original'); expect(localStorage.getItem(target)).toBe('Original message'); expect(localStorage.getItem(oldKey)).toBe(raw)
  localStorage.removeItem(target); transferMemberDraft('swarm',member,'original'); expect(localStorage.getItem(target)).toBeNull()
  localStorage.setItem(oldKey,JSON.stringify({scope:'work',draft:'Updated legacy message'})); localStorage.setItem(target,'New session message')
  transferMemberDraft('swarm',member,'original'); expect(localStorage.getItem(target)).toBe('New session message')
})
it.each(['group','main','foreign-role','old-work'])('does not move a %s draft into this member', scope => {
  localStorage.setItem(oldKey,JSON.stringify({scope,draft:'Private message'}));transferMemberDraft('swarm',member,'original');expect(localStorage.getItem(target)).toBeNull()
})
