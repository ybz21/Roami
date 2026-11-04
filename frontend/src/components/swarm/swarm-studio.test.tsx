// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import SwarmStudio from './SwarmStudio'

const state = vi.hoisted(() => ({ create: vi.fn(), motion: vi.fn(), dispose: vi.fn(), update: vi.fn(), select: vi.fn(), reduced: false }))
vi.mock('./studio/studio-scene', () => ({ createStudio: state.create }))
vi.mock('../../layout', () => ({ useLayout: () => ({ coarse: false, reducedMotion: state.reduced }) }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
const nodes = [{ id: 'member', name: 'Member', executor: 'codex', state: 'idle' }]
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear(); state.reduced = false
  state.create.mockReturnValue({ motion: state.motion, dispose: state.dispose, update: state.update, select: state.select })
})
afterEach(cleanup)

it('releases the renderer outside the collaboration tab and restores it on return', async () => {
  const select = vi.fn()
  const view = render(<SwarmStudio historical nodes={nodes} selected="member" onSelect={select} />)
  await waitFor(() => expect(state.create).toHaveBeenCalledOnce())
  expect(state.motion).toHaveBeenLastCalledWith(true, false, true)
  view.rerender(<SwarmStudio historical active={false} nodes={nodes} selected="member" onSelect={select} />)
  expect(state.dispose).toHaveBeenCalledOnce()
  view.rerender(<SwarmStudio historical nodes={nodes} selected="member" onSelect={select} />)
  await waitFor(() => expect(state.create).toHaveBeenCalledTimes(2))
  expect(state.select).toHaveBeenLastCalledWith('member')
})

it('honors saved motion and reduced motion preferences in historical scenes', async () => {
  localStorage.setItem('roami.swarm.motion', 'off'); state.reduced = true
  render(<SwarmStudio historical nodes={nodes} selected="member" onSelect={vi.fn()} />)
  await waitFor(() => expect(state.create).toHaveBeenCalledOnce())
  expect(state.motion).toHaveBeenLastCalledWith(false, true, true)
  fireEvent.click(screen.getByRole('button', { name: 'swarm.studio.motionOff' }))
  expect(localStorage.getItem('roami.swarm.motion')).toBe('on')
  expect(state.motion).toHaveBeenLastCalledWith(true, true, true)
})

it('recovers a WebGL failure without dropping member selection', async () => {
  state.create.mockImplementationOnce(() => { throw new Error('NO_WEBGL') })
  const select = vi.fn()
  render(<SwarmStudio nodes={nodes} selected="member" onSelect={select} />)
  await screen.findByText('swarm.studio.unavailable')
  fireEvent.click(screen.getByRole('button', { name: 'agent.retry' }))
  await waitFor(() => expect(state.create).toHaveBeenCalledTimes(2))
  expect(state.select).toHaveBeenLastCalledWith('member')
  fireEvent.click(screen.getByRole('button', { name: 'Member' }))
  expect(select).toHaveBeenCalledWith('member')
})
