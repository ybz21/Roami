// @vitest-environment jsdom
import { cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { PageActivityProvider } from '../../page-activity'
import SwarmStudio from './SwarmStudio'
const state = vi.hoisted(() => ({ create: vi.fn(), dispose: vi.fn() }))
vi.mock('./studio/studio-scene', () => ({ createStudio: state.create }))
vi.mock('../../layout', () => ({ useLayout: () => ({ coarse: false, reducedMotion: false }) }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
afterEach(cleanup)
it('disposes its WebGL scene while the owning page is hidden and rebuilds on return', async () => {
 state.create.mockReturnValue({ dispose: state.dispose, motion: vi.fn(), update: vi.fn(), select: vi.fn() })
 const view = (active: boolean) => <PageActivityProvider active={active}><SwarmStudio nodes={[]} selected="" onSelect={() => {}} /></PageActivityProvider>
 const rendered = render(view(true)); await waitFor(() => expect(state.create).toHaveBeenCalledOnce())
 rendered.rerender(view(false)); expect(state.dispose).toHaveBeenCalledOnce()
 rendered.rerender(view(true)); await waitFor(() => expect(state.create).toHaveBeenCalledTimes(2))
 rendered.unmount(); expect(state.dispose).toHaveBeenCalledTimes(2)
})
