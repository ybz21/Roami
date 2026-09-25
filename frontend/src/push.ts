// Web Push 订阅（24 稿 §6）：向浏览器要一个订阅，交给本部署的后端存着；后端用自己的 VAPID 密钥
// 签名后经浏览器厂商的网关推到这台设备。不依赖任何中心服务。
// 需要：安全上下文 + 受信任证书（自签证书 iPhone 收不到）+ 加到主屏（iOS）。
import { api } from './api'

const DEVICE_KEY = 'roami.push.device'

export function pushSupported(): boolean {
  return typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

function deviceId(): string {
  try {
    let id = localStorage.getItem(DEVICE_KEY)
    if (!id) { id = Math.random().toString(36).slice(2, 10) + Date.now().toString(36); localStorage.setItem(DEVICE_KEY, id) }
    return id
  } catch { return 'anon' }
}

function b64ToBytes(b64: string): Uint8Array {
  const pad = '='.repeat((4 - (b64.length % 4)) % 4)
  const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(raw, (c) => c.charCodeAt(0))
}

/** 这台设备现在有没有订阅（问浏览器，不问后端） */
export async function pushEnabled(): Promise<boolean> {
  if (!pushSupported()) return false
  try {
    const reg = await navigator.serviceWorker.ready
    return !!(await reg.pushManager.getSubscription())
  } catch { return false }
}

export type PushEnableResult = 'ok' | 'denied' | 'unsupported' | 'failed'

export async function enablePush(): Promise<PushEnableResult> {
  if (!pushSupported()) return 'unsupported'
  const perm = await Notification.requestPermission()
  if (perm !== 'granted') return 'denied'
  try {
    const reg = await navigator.serviceWorker.ready
    const { publicKey } = (await api('GET', '/push/vapid')).data
    let sub = await reg.pushManager.getSubscription()
    if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(publicKey) as BufferSource })
    await api('POST', '/push/subscribe', { device: deviceId(), ua: navigator.userAgent.slice(0, 120), subscription: sub.toJSON() })
    return 'ok'
  } catch (e) {
    console.error('push subscribe failed', e)
    return 'failed'
  }
}

export async function disablePush(): Promise<void> {
  try {
    const reg = await navigator.serviceWorker.ready
    const sub = await reg.pushManager.getSubscription()
    if (sub) await sub.unsubscribe()
  } catch { /* 没订阅 */ }
  await api('DELETE', '/push/subscribe', { device: deviceId() }).catch(() => {})
}

/** 角标：需要你的条数。不支持的浏览器静默 */
export function setBadge(n: number) {
  try {
    const nav = navigator as any
    if (n > 0) nav.setAppBadge?.(n); else nav.clearAppBadge?.()
  } catch { /* ignore */ }
}
