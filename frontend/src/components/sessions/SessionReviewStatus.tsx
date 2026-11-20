import { useI18n } from '../../i18n'
import { useSessionOverview } from '../../session-overview'
import './session-review.css'

export default function SessionReviewStatus({ name, open }: { name: string; open?: (name: string) => void }) {
  const { t } = useI18n()
  const { value } = useSessionOverview()
  const review = value.find(item => item.name === name)?.review
  if (!review) return null
  const showPeer = open && value.some(item => item.name === review.peer)
  return <div className="tt-session-review">
    <span role="status">
      {t(`session.review.phase.${review.phase}`)}
      {review.round > 0 && <span className="tt-review-round">{t('session.review.round', { round: review.round })}</span>}
    </span>
    {showPeer && <button type="button" className="tt-act" onClick={() => open?.(review.peer)}>
      {t(review.role === 'author' ? 'session.review.openReviewer' : 'session.review.openAuthor')}
    </button>}
  </div>
}
