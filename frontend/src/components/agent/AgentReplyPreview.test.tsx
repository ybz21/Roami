// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentReplyPreview from './AgentReplyPreview'
import { ChatMessage } from '../chat/Message'
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false, size: 'expanded' }) }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
afterEach(cleanup)
it('renders provisional Markdown without loading images while approved messages retain normal rendering', async () => {
  render(<><AgentReplyPreview messageId="candidate" resolveResource={href => href} value={{ text: '# Draft\n![preview media](https://fixture.invalid/draft.png)', state: 'generating', clipped: false }} />
    <ChatMessage side="native" results={{}} m={{ id: 'final', role: 'assistant', blocks: [{ kind: 'text', text: '# Final\n![approved media](https://fixture.invalid/final.png)' }] }} /></>)
  await screen.findByRole('heading', { name: 'Draft' })
  await screen.findByRole('img', { name: 'approved media' })
  expect(screen.queryByRole('img', { name: 'preview media' })).toBeNull()
  expect(screen.getByText('agent.replyPreview.generating')).toBeTruthy()
})
