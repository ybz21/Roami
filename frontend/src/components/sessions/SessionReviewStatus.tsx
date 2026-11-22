import { useState } from 'react'
import { Modal } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { useSessionOverview } from '../../session-overview'
import MobileSubPage from '../MobileSubPage'
import './session-review.css'

type ReviewVerdict = { round: number; version: string; verdict: 'approved' | 'changes_requested'; result: string }

export default function SessionReviewStatus({ name, open }: { name: string; open?: (name: string) => void }) {
  const { t } = useI18n()
  const { phone } = useLayout()
  const { value } = useSessionOverview()
  const review = value.find(item => item.name === name)?.review
  const [history, setHistory] = useState<{ session: string; rounds?: ReviewVerdict[]; error?: boolean }>()
  const [continuing, setContinuing] = useState(false)
  const [continueFailed, setContinueFailed] = useState(false)
  if (!review) return null
  const showPeer = open && value.some(item => item.name === review.peer)
  const showRound = review.round > 0 && !['stale', 'checking', 'clean'].includes(review.phase)
  const path = `/sessions/${encodeURIComponent(name)}/review`
  const loadHistory = async () => {
    setHistory({ session: name })
    try {
      const response = await api('GET', `${path}/history`)
      setHistory(current => current?.session === name ? { session: name, rounds: response.data.rounds } : current)
    } catch {
      setHistory(current => current?.session === name ? { session: name, error: true } : current)
    }
  }
  const continueReview = async () => {
    setContinueFailed(false)
    setContinuing(true)
    try {
      await api('POST', `${path}/continue`, { round: review.round })
      window.dispatchEvent(new Event('roami:sessions-changed'))
    } catch {
      setContinueFailed(true)
    } finally {
      setContinuing(false)
    }
  }
  const dismissHistory = () => setHistory(undefined)
  const historyTitle = t('session.review.history')
  const historyContent = history?.session === name && (
    <div className="tt-review-history" aria-busy={!history.rounds && !history.error}>
      {history.error ? <p role="alert">{t('session.review.historyFailed')}</p> : history.rounds?.length === 0 ? <p>{t('session.review.historyEmpty')}</p> :
        history.rounds && [...history.rounds].reverse().map(round => <section key={round.round}>
          <strong>{t('session.review.round', { round: round.round })} · {t(`session.review.verdict.${round.verdict}`)}</strong>
          <code>{round.version}</code>
          <p>{round.result}</p>
        </section>)}
    </div>
  )
  return <div className="tt-session-review">
    <span role="status">
      {t(`session.review.phase.${review.phase}`)}
      {showRound && <span className="tt-review-round">{t('session.review.round', { round: review.round })}</span>}
      {review.newVersion && <span className="tt-review-round">{t('session.review.newVersion')}</span>}
    </span>
    {showPeer && <button type="button" className="tt-act" onClick={() => open?.(review.peer)}>
      {t(review.role === 'author' ? 'session.review.openReviewer' : 'session.review.openAuthor')}
    </button>}
    {review.round > 0 && <button type="button" className="tt-act" onClick={() => void loadHistory()}>{historyTitle}</button>}
    {review.phase === 'limit' && showPeer && <button type="button" className="tt-act" disabled={continuing} onClick={() => void continueReview()}>{t('session.review.resume')}</button>}
    {continueFailed && review.phase === 'limit' && <span role="alert">{t('session.review.resumeFailed')}</span>}
    {historyContent && (phone ?
      <MobileSubPage title={historyTitle} dialogLabel={historyTitle} onBack={dismissHistory} layer="session" search={false}>{historyContent}</MobileSubPage> :
      <Modal open title={historyTitle} onCancel={dismissHistory} footer={null}>{historyContent}</Modal>)}
  </div>
}
