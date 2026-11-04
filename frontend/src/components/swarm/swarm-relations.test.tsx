// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import SwarmRelations from './SwarmRelations'
import type { SwarmSnapshot, SwarmWork } from './swarm-protocol'

vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
afterEach(cleanup)

function work(id: string, member: string, title: string, dependencies: SwarmWork['dependencies'] = []): SwarmWork {
  return { id, member_name: member, title, executor: 'native', goal: 'Full private instructions remain in task details', acceptance: 'Read the stored artifacts', integration: 0, task_id: null, revision: null, state: 'planning', dispatch_error: null, dependencies, attempt: null }
}
function snapshot(): SwarmSnapshot {
  return { id: 'sw-real', name: 'Actual team', goal: 'Actual goal', mainConversationId: 'bound-conversation', revision: 2, sequence: 8, paused: true, archived: false, state: 'planning', target: {}, posts: [], mainMessages: [], work: [work('gamma', 'Publisher', 'Prepare publication'), work('alpha', 'Researcher', 'Produce source report'), work('beta', 'Reviewer', 'Check source report', [{ upstreamId: 'alpha', revision: 3 }])] }
}
function card(member: string) {
  return screen.getByRole('button', { name: member, pressed: false }).closest('article')!
}
it('shows the bound Main and each real assignment without exposing full instructions', () => {
  const main = vi.fn(), select = vi.fn()
  render(<SwarmRelations data={snapshot()} selected="main" onMain={main} onSelect={select} />)
  fireEvent.click(screen.getByRole('button', { name: /Roami Main/ }))
  expect(main).toHaveBeenCalledOnce()
  expect(within(card('Researcher')).getByText('Produce source report', { selector: '.swarm-relation-duty' })).toBeTruthy()
  expect(screen.queryByText('Full private instructions remain in task details')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Publisher', pressed: false }))
  expect(select).toHaveBeenCalledWith('gamma')
})
it('derives both directions only from work IDs, independently of member order or names', () => {
  const select = vi.fn()
  render(<SwarmRelations data={snapshot()} selected="main" onMain={vi.fn()} onSelect={select} />)
  const reviewer = within(card('Reviewer')), researcher = within(card('Researcher')), publisher = within(card('Publisher'))
  const up = reviewer.getByText('swarm.relations.upstream').parentElement!
  expect(within(up).getByRole('button', { name: /Researcher.*Produce source report/ })).toBeTruthy()
  expect(within(up).queryByRole('button', { name: /Publisher/ })).toBeNull()
  const down = researcher.getByText('swarm.relations.downstream').parentElement!
  fireEvent.click(within(down).getByRole('button', { name: /Reviewer.*Check source report/ }))
  expect(select).toHaveBeenCalledWith('beta')
  expect(publisher.getAllByText('swarm.relations.none')).toHaveLength(2)
})
it('reports a missing upstream explicitly instead of guessing or dropping the dependency', () => {
  const data = snapshot(); data.work[2].dependencies = [{ upstreamId: 'not-in-snapshot', revision: 9 }]
  render(<SwarmRelations data={data} selected="main" onMain={vi.fn()} onSelect={vi.fn()} />)
  expect(within(card('Reviewer')).getByText('swarm.relations.unavailable')).toBeTruthy()
  expect(within(card('Researcher')).getAllByText('swarm.relations.none')).toHaveLength(2)
  expect(screen.queryByText('not-in-snapshot')).toBeNull()
})
it('does not invent a Main binding or members for incomplete snapshots', () => {
  render(<SwarmRelations data={{ ...snapshot(), mainConversationId: '', work: [] }} selected="main" onMain={vi.fn()} onSelect={vi.fn()} />)
  expect(screen.queryByRole('button', { name: /Roami Main/ })).toBeNull()
  expect(screen.getByText('swarm.relations.mainUnavailable')).toBeTruthy()
  expect(screen.getByText('swarm.managed.planning')).toBeTruthy()
  expect(screen.queryByRole('article')).toBeNull()
})
