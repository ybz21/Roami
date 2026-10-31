type Fields = Record<string, unknown>
const fields = (value: unknown): Fields => value && typeof value === 'object' && !Array.isArray(value) ? value as Fields : {}
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= 1e12
export type AudioMeasurement = { key: string; value: number | null }
const scores = ['in_window_reward', 'out_window_reward'] as const
const groups = {
  in_window: ['pesq_wb', 'stoi', 'lsd_full', 'lsd_4_8kHz', 'f0_corr', 'dnsmos_sig', 'dnsmos_bak', 'dnsmos_ovl'],
  out_window: ['out_si_sdr_db', 'out_n_samples'],
} as const

export function audioVerificationEvidence(value: unknown): { scores: AudioMeasurement[]; metrics: AudioMeasurement[] } | null {
  const native = fields(value)
  if (native.native_verifier_ran !== true || native.grade_scope !== 'original_media_verifier_plus_frozen_delivery_checks') return null
  const audio = fields(native.native_audio_diagnostic)
  const summary = scores.filter(key => Object.prototype.hasOwnProperty.call(audio, key)).map(key => ({ key, value: finite(audio[key]) && Number(audio[key]) >= 0 && Number(audio[key]) <= 1 ? Number(audio[key]) : null }))
  const metrics: AudioMeasurement[] = []
  for (const [group, keys] of Object.entries(groups)) {
    const values = fields(audio[group])
    for (const key of keys) if (Object.prototype.hasOwnProperty.call(values, key)) metrics.push({ key, value: finite(values[key]) ? Number(values[key]) : null })
  }
  return summary.length || metrics.length ? { scores: summary, metrics } : null
}
