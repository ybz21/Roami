package com.roami.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.webkit.CookieManager
import androidx.core.app.NotificationCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * 通知来源（Gotify / ntfy 的做法）：前台服务常驻一条 WebSocket 到 /api/events/ws，
 * 事件来了自己弹本地通知。不走 Google 的 FCM——自托管软件没有发布者账号可用，国产手机也常没 Google 服务。
 * 登录态用 WebView 里的 Cookie；还没登录就每 15s 看一眼，登录了才连。
 */
class EventService : Service() {
    private lateinit var base: String
    private lateinit var host: String
    private var ws: WebSocket? = null
    private var backoff = 5_000L
    private val main = Handler(Looper.getMainLooper())
    private var stopped = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) { stopped = true; ws?.close(1000, null); stopSelf(); return START_NOT_STICKY }
        val b = intent?.getStringExtra("base") ?: Prefs(this).current ?: run { stopSelf(); return START_NOT_STICKY }
        if (::base.isInitialized && base == b && ws != null) return START_STICKY
        base = b
        host = runCatching { java.net.URI(base).host }.getOrNull() ?: base
        channels()
        startFg(getString(R.string.link_connecting, host))
        stopped = false
        ws?.close(1000, null); ws = null
        connect()
        return START_STICKY
    }

    private fun channels() {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CH_LINK, getString(R.string.ch_link), NotificationManager.IMPORTANCE_MIN))
        nm.createNotificationChannel(NotificationChannel(CH_EVENTS, getString(R.string.ch_events), NotificationManager.IMPORTANCE_HIGH).apply {
            description = getString(R.string.ch_events_desc)
        })
    }

    private fun startFg(text: String) {
        val stop = PendingIntent.getService(this, 0, Intent(this, EventService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE)
        val open = PendingIntent.getActivity(this, 0, Intent(this, WebActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = NotificationCompat.Builder(this, CH_LINK)
            .setSmallIcon(R.drawable.ic_stat).setContentTitle("Roami").setContentText(text)
            .setContentIntent(open).addAction(0, getString(R.string.link_stop), stop)
            .setOngoing(true).setPriority(NotificationCompat.PRIORITY_MIN).setSilent(true).build()
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIF_LINK, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC) else startForeground(NOTIF_LINK, n)
    }

    private fun client(): OkHttpClient {
        val tm = Tls.Pinned(this, host)
        return OkHttpClient.Builder()
            .sslSocketFactory(Tls.sslContext(tm).socketFactory, tm)
            .hostnameVerifier { h, _ -> h == host } // 指纹已经核过；自签证书的 SAN 常不带这个地址
            .pingInterval(30, TimeUnit.SECONDS)
            .build()
    }

    private fun connect() {
        if (stopped) return
        val cookie = CookieManager.getInstance().getCookie(base)
        if (cookie.isNullOrBlank()) { // 还没登录
            startFg(getString(R.string.link_login))
            main.postDelayed({ connect() }, 15_000)
            return
        }
        val wsUrl = base.replaceFirst("http", "ws") + "/api/events/ws"
        val req = Request.Builder().url(wsUrl).header("Cookie", cookie).build()
        ws = client().newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                backoff = 5_000
                main.post { startFg(getString(R.string.link_connected, host)) }
            }
            override fun onMessage(webSocket: WebSocket, text: String) { runCatching { onEvent(JSONObject(text)) } }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { retry(response?.code) }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { retry(null) }
        })
    }

    private fun retry(code: Int?) {
        if (stopped) return
        ws = null
        main.post { startFg(if (code == 401) getString(R.string.link_login) else getString(R.string.link_connecting, host)) }
        main.postDelayed({ connect() }, backoff)
        backoff = (backoff * 2).coerceAtMost(60_000)
    }

    private fun onEvent(o: JSONObject) {
        val type = o.optString("type")
        if (!type.startsWith("session.") && type != "test") return
        val session = o.optString("session")
        val label = o.optString("title").ifBlank { o.optString("label") }
        val waiting = type == "session.waiting"
        val title = when (type) {
            "session.waiting" -> getString(R.string.event_waiting_title, label)
            "session.done" -> getString(R.string.event_done_title, label)
            else -> label
        }
        val body = o.optString("body")
        val open = PendingIntent.getActivity(this, session.hashCode(),
            Intent(this, WebActivity::class.java).putExtra("path", "/#/inbox/" + java.net.URLEncoder.encode(session, "UTF-8")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val b = NotificationCompat.Builder(this, CH_EVENTS)
            .setSmallIcon(R.drawable.ic_stat).setContentTitle(title).setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(open).setAutoCancel(!waiting).setPriority(NotificationCompat.PRIORITY_HIGH)
            .setOngoing(waiting).setOnlyAlertOnce(true)
        if (waiting) {
            b.setRequestPromotedOngoing(true)
                .setShortCriticalText(getString(R.string.event_waiting_chip))
        }
        val actions = o.optJSONArray("actions")
        if (actions != null) for (i in 0 until actions.length()) {
            val a = actions.getString(i)
            val key = when (a) { "allow" -> "Enter"; "deny" -> "Escape"; else -> continue }
            val pi = PendingIntent.getBroadcast(this, (session + a).hashCode(),
                Intent(this, ActionReceiver::class.java)
                    .putExtra("base", base).putExtra("session", session).putExtra("key", key)
                    .putExtra("nid", session.hashCode()).putExtra("title", title).putExtra("body", body),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            b.addAction(0, getString(if (a == "allow") R.string.act_allow else R.string.act_deny), pi)
        }
        // 同一会话复用一条：等你 → 做完 只更新，不叠一摞
        getSystemService(NotificationManager::class.java).notify(session.hashCode(), b.build())
    }

    override fun onDestroy() { stopped = true; ws?.close(1000, null); super.onDestroy() }

    companion object {
        const val CH_LINK = "link"
        const val CH_EVENTS = "events"
        const val NOTIF_LINK = 1
        const val ACTION_STOP = "com.roami.app.STOP"
    }
}
