import { useState } from 'react'
import { useI18n } from '../../i18n'
import VoiceInput from '../chat/VoiceInput'

export default function SpeechTranscriptionTest() {
  const { t } = useI18n()
  const [text, setText] = useState('')
  return <section className="tt-speech-test" aria-label={t('settings.speechTest')}>
    <h3>{t('settings.speechTest')}</h3>
    <div className="tt-speech-test-actions"><VoiceInput test accent="var(--accent)" scope="speech-settings" onResult={setText} /></div>
    <p role="status">{text}</p>
  </section>
}
