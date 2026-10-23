package com.roami.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.Manifest
import android.content.Intent
import android.content.res.Configuration
import android.content.pm.ServiceInfo
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import android.webkit.CookieManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import java.util.Locale
import kotlin.concurrent.thread

/**
 * 通知来源（Gotify / ntfy 的做法）：前台服务常驻一条 WebSocket 到 /api/events/ws，
 * 事件来了自己弹本地通知。不走 Google 的 FCM——自托管软件没有发布者账号可用，国产手机也常没 Google 服务。
 * 登录态用 WebView 里的 Cookie；还没登录就每 15s 看一眼，登录了才连。
 */
class EventService : Service() {
    @Volatile private lateinit var base: String
    private lateinit var host: String
    private var ws: WebSocket? = null
    private var backoff = 5_000L
    private val main = Handler(Looper.getMainLooper())
    @Volatile private var stopped = false
    @Volatile private var refreshing = false
    private var eventRevision = 0L
    private var unfinished = 0
    private var unfinishedAt = 0L
    private val capsuleState = TaskCapsuleState()
    private lateinit var eventRecovery: TaskEventRecovery
    private val reconnect = Runnable { connect() }
    private var displayedCapsule: CapsuleTask? = null
    private var displayedCount = 0
    private var foregroundNotificationId = NOTIF_LINK
    private var linkText = ""
    private val capsuleTimeout = Runnable { renderForeground() }
    private val statusLoop = object : Runnable {
        override fun run() { refreshStatus(); main.postDelayed(this, 15_000) }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) { stopped = true; ws?.close(1000, null); getSystemService(NotificationManager::class.java).cancel(NOTIF_ATTENTION); capsuleState.reset(); if (::base.isInitialized) { Prefs(this).saveTaskCards(base, emptyList()); sendBroadcast(Intent(ACTION_TASK_CARDS_CHANGED).setPackage(packageName).putExtra("base", base)) }; stopSelf(); return START_NOT_STICKY }
        if (intent?.action == ACTION_RESOLVE && ::base.isInitialized) {
            if (intent.getStringExtra("base") != base) return START_STICKY
            eventRevision++
            intent.getStringExtra("session")?.let { capsuleState.resolve(it, SystemClock.elapsedRealtime(), intent.getStringExtra("prompt")) }
            renderForeground(); refreshStatus(); return START_STICKY
        }
        if (intent?.action == ACTION_ACKNOWLEDGE && ::base.isInitialized) {
            if (intent.getStringExtra("base") != base) return START_STICKY
            eventRevision++
            intent.getStringExtra("session")?.let { capsuleState.acknowledgeFailure(it) }
            renderForeground(); return START_STICKY
        }
        if (intent?.action == ACTION_REFRESH && ::base.isInitialized) { refreshStatus(); return START_STICKY }
        val b = intent?.getStringExtra("base") ?: Prefs(this).current ?: run { stopSelf(); return START_NOT_STICKY }
        if (::base.isInitialized && base == b) {
            if (ws == null) connect()
            refreshStatus()
            return START_STICKY
        }
        base = b
        eventRecovery = Prefs(this).taskEvents(base)
        capsuleState.reset()
        displayedCapsule = null
        main.removeCallbacks(capsuleTimeout)
        unfinished = 0
        unfinishedAt = 0L
        host = runCatching { java.net.URI(base).host }.getOrNull() ?: base
        channels()
        stopped = false
        startFg(getString(R.string.link_connecting, host))
        main.removeCallbacks(reconnect)
        ws?.close(1000, null); ws = null
        connect()
        main.removeCallbacks(statusLoop)
        main.post(statusLoop)
        return START_STICKY
    }

    private fun channels() {
        val nm = getSystemService(NotificationManager::class.java)
        nm.activeNotifications.filter { it.notification.extras.containsKey("roami.taskState") &&
            !it.notification.extras.containsKey("roami.base") }.forEach { nm.cancel(it.tag, it.id) }
        nm.cancel("task-progress", 3)
        nm.createNotificationChannel(NotificationChannel(CH_LINK, getString(R.string.ch_link), NotificationManager.IMPORTANCE_MIN).apply { setShowBadge(false) })
        nm.createNotificationChannel(NotificationChannel(CH_EVENTS, getString(R.string.ch_events), NotificationManager.IMPORTANCE_HIGH).apply {
            description = getString(R.string.ch_events_desc)
            setShowBadge(false)
        })
        nm.createNotificationChannel(NotificationChannel(CH_CAPSULE, getString(R.string.ch_capsule), NotificationManager.IMPORTANCE_DEFAULT).apply {
            setShowBadge(false)
        })
        nm.createNotificationChannel(NotificationChannel(CH_ATTENTION, getString(R.string.ch_attention), NotificationManager.IMPORTANCE_LOW).apply { setShowBadge(true) })
    }

    private fun startFg(text: String) {
        linkText = text
        renderForeground()
    }

    private fun renderForeground() {
        if (stopped || !::base.isInitialized) return
        main.removeCallbacks(capsuleTimeout)
        val now = SystemClock.elapsedRealtime()
        val task = if (Build.VERSION.SDK_INT >= 36) capsuleState.current(now) else null
        val tasks = capsuleState.pending(now)
        if (Prefs(this).saveTaskCards(base, tasks)) sendBroadcast(Intent(ACTION_TASK_CARDS_CHANGED).setPackage(packageName).putExtra("base", base))
        capsuleState.nextChangeDelay(now)?.let { main.postDelayed(capsuleTimeout, it) }
        if (task != null) {
            if (task != displayedCapsule || tasks.size != displayedCount) {
                val n = TaskNotification.build(this, base, task.session, task.title, task.body,
                    task.state, task.actions, capsule = true, prompt = task.prompt, choices = task.choices,
                    selectionMode = task.selectionMode, attentionCount = tasks.size)
                foreground(NOTIF_CAPSULE, n)
                displayedCapsule = task
                displayedCount = tasks.size
            }
            return
        }
        if (displayedCapsule == null && linkText.isEmpty()) return
        displayedCapsule = null
        displayedCount = 0
        val stop = PendingIntent.getService(this, 0, Intent(this, EventService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE)
        val open = PendingIntent.getActivity(this, 0, Intent(this, WebActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = NotificationCompat.Builder(this, CH_LINK)
            .setSmallIcon(R.drawable.ic_stat).setContentTitle("Roami").setContentText(linkText)
            .setContentIntent(open).addAction(0, getString(R.string.link_stop), stop)
            .setOngoing(true).setPriority(NotificationCompat.PRIORITY_MIN).setSilent(true).build()
        foreground(NOTIF_LINK, n)
    }

    private fun foreground(id: Int, n: Notification) {
        if (Build.VERSION.SDK_INT >= 29) startForeground(id, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC) else startForeground(id, n)
        if (foregroundNotificationId != id) getSystemService(NotificationManager::class.java).cancel(foregroundNotificationId)
        foregroundNotificationId = id
    }

    private fun client(server: String = base): OkHttpClient {
        val serverHost = java.net.URI(server).host
        val tm = Tls.Pinned(this, serverHost)
        return OkHttpClient.Builder()
            .sslSocketFactory(Tls.sslContext(tm).socketFactory, tm)
            .hostnameVerifier { h, _ -> h == serverHost } // 指纹已经核过；自签证书的 SAN 常不带这个地址
            .pingInterval(30, TimeUnit.SECONDS)
            .build()
    }

    private fun connect() {
        main.removeCallbacks(reconnect)
        if (stopped || ws != null) return
        val cookie = CookieManager.getInstance().getCookie(base)
        if (cookie.isNullOrBlank()) { // 还没登录
            startFg(getString(R.string.link_login))
            main.postDelayed(reconnect, 15_000)
            return
        }
        val wsUrl = base.replaceFirst("http", "ws") + "/api/events/ws"
        val version = packageManager.getPackageInfo(packageName, 0).versionName ?: "unknown"
        val req = Request.Builder().url(wsUrl).header("Cookie", cookie).header("User-Agent", "RoamiApp/$version").build()
        ws = client().newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                main.post {
                    if (stopped || ws !== webSocket) return@post
                    backoff = 5_000
                    startFg(getString(R.string.link_connected, host)); refreshStatus()
                }
            }
            override fun onMessage(webSocket: WebSocket, text: String) {
                main.post { if (!stopped && ws === webSocket) runCatching { onEvent(JSONObject(text)) } }
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                main.post { if (ws === webSocket) retry(response?.code) }
            }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                main.post { if (ws === webSocket) retry(null) }
            }
        })
    }

    private fun retry(code: Int?) {
        if (stopped) return
        ws = null
        main.post { startFg(if (code == 401) getString(R.string.link_login) else getString(R.string.link_connecting, host)) }
        main.removeCallbacks(reconnect)
        main.postDelayed(reconnect, backoff)
        backoff = (backoff * 2).coerceAtMost(60_000)
    }

    private fun onEvent(o: JSONObject) {
        val type = o.optString("type")
        if (type == "session.waiting" || type == "session.done" || type == "session.error") refreshStatus()
        if (type !in setOf("session.waiting", "session.done", "session.error", "test", "agent.message")) return
        val agentMessage = type == "agent.message"
        val session = o.optString("session")
        val title = o.optString("title").ifBlank { o.optString("label") }
        val notificationLocale = o.optString("locale").takeIf { it == "zh-CN" || it == "en-US" }
        val localized = if (notificationLocale != null) createConfigurationContext(Configuration(resources.configuration).apply { setLocale(Locale.forLanguageTag(notificationLocale)) }) else this
        val body = if (agentMessage && o.optBoolean("hidePreview")) localized.getString(R.string.agent_new_message) else o.optString("body")
        if (!agentMessage && type != "test") {
            if (session.isBlank()) return
            val actions = o.optJSONArray("actions")?.let { list -> (0 until list.length()).map { list.optString(it) } } ?: emptyList()
            val prompt = o.optString("prompt")
            val choices = TaskChoice.read(o.optJSONArray("choices"))
            val selectionMode = o.optString("selectionMode", "single")
            val eventBase = base
            main.post {
                if (stopped || base != eventBase) return@post
                if (!eventRecovery.accept(o.optLong("id"))) return@post
                eventRevision++
                val now = SystemClock.elapsedRealtime()
                val state = when (type) {
                    "session.waiting" -> TaskNoticeState.WAITING
                    "session.error" -> TaskNoticeState.FAILED
                    else -> TaskNoticeState.FINISHED
                }
                capsuleState.onEvent(CapsuleTask(session, title, body, state, actions, prompt, choices, selectionMode), o.optLong("id"), now)
                try {
                    renderForeground()
                    if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                        receipt(o.optLong("id"), "blocked", session)
                        return@post
                    }
                    val notice = TaskNotification.build(localized, base, session, title, body, state, actions, prompt = prompt, choices = choices,
                        selectionMode = selectionMode, attentionCount = capsuleState.pending(now).size)
                    getSystemService(NotificationManager::class.java).notify(TaskNotification.tag(base), TaskNotification.id(session), notice)
                    Prefs(this).saveTaskEvents(base, eventRecovery)
                    receipt(o.optLong("id"), "posted", session)
                } catch (error: Exception) {
                    android.util.Log.e("RoamiEvents", "Task notification failed", error)
                    receipt(o.optLong("id"), "error", session)
                }
            }
            return
        }
        val notificationKey = if (agentMessage) AgentNotification.key(o) else "test"
        val path = if (agentMessage) AgentNotification.path(o) else "/#/projects"
        val open = PendingIntent.getActivity(this, notificationKey.hashCode(),
            Intent(this, WebActivity::class.java).putExtra("path", path).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val b = NotificationCompat.Builder(this, CH_EVENTS)
            .setSmallIcon(R.drawable.ic_stat).setContentTitle(title).setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(open).setAutoCancel(true).setPriority(NotificationCompat.PRIORITY_HIGH)
        if (agentMessage) b.setNumber(o.optInt("badge", 0).coerceAtLeast(0))
        getSystemService(NotificationManager::class.java).notify(notificationKey.hashCode(), b.build())
    }

    private fun refreshStatus() {
        if (stopped || refreshing || !::base.isInitialized) return
        val cookie = CookieManager.getInstance().getCookie(base)
        if (cookie.isNullOrBlank()) { invalidateStatus(clearTasks = true); return }
        refreshing = true
        val statusBase = base
        val statusRevision = eventRevision
        thread {
            try {
                val http = client(statusBase)
                val req = Request.Builder().url("$statusBase/api/sessions/overview").header("Cookie", cookie).build()
                http.newCall(req).execute().use { response ->
                    if (!response.isSuccessful) { invalidateStatus(clearTasks = response.code == 401 || response.code == 403, statusBase = statusBase); return@use }
                    val items = JSONObject(response.body?.string() ?: "").getJSONObject("data").getJSONArray("items")
                    val snapshot = WidgetSnapshot.fromOverview(items).copy(unfinished = unfinishedCount(http, cookie, statusBase))
                    val live = (0 until items.length()).mapNotNull { items.optJSONObject(it)?.optString("name") }.toSet()
                    main.post {
                        if (stopped || base != statusBase) return@post
                        // A response started before a task event must not erase its newer question.
                        if (eventRevision != statusRevision) {
                            main.postDelayed({ if (!stopped && base == statusBase) refreshStatus() }, 250)
                            return@post
                        }
                        snapshot.save(this, statusBase)
                        StatusWidget.update(this)
                        updateAttention(snapshot.attentionCount)
                        updateTaskCapsule(snapshot, live)
                    }
                    recoverTaskEvents(http, cookie, statusBase, snapshot.runningItems.map { it.name }.toSet())
                }
            } catch (_: Exception) {
                invalidateStatus(statusBase = statusBase)
            } finally { refreshing = false }
        }
    }

    private fun recoverTaskEvents(http: OkHttpClient, cookie: String, statusBase: String, running: Set<String>) {
        runCatching {
            val req = Request.Builder().url("$statusBase/api/inbox?limit=100").header("Cookie", cookie).build()
            http.newCall(req).execute().use { response ->
                if (!response.isSuccessful) return@use
                val items = JSONObject(response.body?.string() ?: "").getJSONObject("data").getJSONArray("items")
                main.post {
                    if (stopped || base != statusBase) return@post
                    eventRecovery.recover(items, System.currentTimeMillis() / 1000, running).forEach { onEvent(it) }
                    main.post { if (!stopped && base == statusBase) Prefs(this).saveTaskEvents(base, eventRecovery) }
                }
            }
        }
    }

    private fun receipt(id: Long, status: String, session: String) {
        if (id <= 0) return
        ws?.send(JSONObject().put("type", "receipt").put("id", id).put("status", status)
            .put("capsule", displayedCapsule?.session == session).toString())
    }

    private fun unfinishedCount(http: OkHttpClient, cookie: String, statusBase: String): Int {
        if (stopped || base != statusBase) return 0
        val now = SystemClock.elapsedRealtime()
        if (unfinishedAt != 0L && now - unfinishedAt < 60_000) return unfinished
        try {
            val req = Request.Builder().url("$statusBase/api/projects").header("Cookie", cookie).build()
            http.newCall(req).execute().use { response ->
                if (response.isSuccessful && !stopped && base == statusBase) {
                    val projects = JSONObject(response.body?.string() ?: "").getJSONObject("data").getJSONArray("projects")
                    unfinished = WidgetSnapshot.unfinishedFromProjects(projects)
                    unfinishedAt = now
                }
            }
        } catch (_: Exception) { }
        if (unfinishedAt == 0L || now - unfinishedAt > 120_000) unfinished = 0
        return unfinished
    }

    private fun invalidateStatus(clearTasks: Boolean = false, statusBase: String = base) {
        main.post {
            if (stopped || base != statusBase) return@post
            unfinished = 0
            unfinishedAt = 0L
            if (WidgetSnapshot.clear(this)) StatusWidget.update(this)
            updateAttention(0)
            if (clearTasks) capsuleState.reset()
            renderForeground()
        }
    }

    private fun updateTaskCapsule(snapshot: WidgetSnapshot, live: Set<String>) {
        val now = SystemClock.elapsedRealtime()
        val waiting = snapshot.waitingItems.map {
            CapsuleTask(it.name, it.label, it.waitingBody.ifBlank { getString(R.string.event_waiting_body) },
                TaskNoticeState.WAITING, prompt = it.prompt, choices = it.choices, selectionMode = it.selectionMode)
        }
        val waitingIds = waiting.map { TaskNotification.id(it.session) }.toSet()
        val nm = getSystemService(NotificationManager::class.java)
        nm.activeNotifications.filter {
            it.tag == TaskNotification.tag(base) && it.notification.channelId == CH_EVENTS && it.notification.flags and Notification.FLAG_ONGOING_EVENT != 0 && it.id !in waitingIds
        }.forEach { nm.cancel(it.tag, it.id) }
        capsuleState.onSnapshot(waiting, now, snapshot.runningItems.map { it.name }.toSet(), live)
        renderForeground()
    }

    private fun updateAttention(count: Int) {
        val nm = getSystemService(NotificationManager::class.java)
        if (count == 0) { nm.cancel(NOTIF_ATTENTION); return }
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val open = PendingIntent.getActivity(this, 410, Intent(this, WebActivity::class.java).putExtra("path", "/#/projects"),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notification = NotificationCompat.Builder(this, CH_ATTENTION)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle(getString(R.string.attention_title, count))
            .setContentText(getString(R.string.attention_body))
            .setContentIntent(open).setNumber(count).setBadgeIconType(NotificationCompat.BADGE_ICON_SMALL)
            .setOnlyAlertOnce(true).setSilent(true).build()
        nm.notify(NOTIF_ATTENTION, notification)
    }

    override fun onDestroy() { stopped = true; main.removeCallbacks(statusLoop); main.removeCallbacks(capsuleTimeout); main.removeCallbacks(reconnect); ws?.close(1000, null); super.onDestroy() }

    companion object {
        const val CH_LINK = "link_v2"
        const val CH_EVENTS = "events_v2"
        const val CH_CAPSULE = "capsule_v1"
        const val CH_ATTENTION = "attention"
        const val NOTIF_LINK = 1
        const val NOTIF_ATTENTION = 2
        const val NOTIF_CAPSULE = 4
        const val ACTION_STOP = "com.roami.app.STOP"
        const val ACTION_REFRESH = "com.roami.app.REFRESH"
        const val ACTION_TASK_CARDS_CHANGED = "com.roami.app.TASK_CARDS_CHANGED"
        const val ACTION_RESOLVE = "com.roami.app.RESOLVE"
        const val ACTION_ACKNOWLEDGE = "com.roami.app.ACKNOWLEDGE"
    }
}
