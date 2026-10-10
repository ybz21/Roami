package com.roami.app

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.webkit.CookieManager
import androidx.core.app.NotificationCompat
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/** Notification actions submit directly to the session; a failed request leaves a retryable alert. */
class ActionReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        val base = intent.getStringExtra("base") ?: return
        val session = intent.getStringExtra("session") ?: return
        val key = intent.getStringExtra("key") ?: return
        val title = intent.getStringExtra("title") ?: ctx.getString(R.string.app_name)
        val body = intent.getStringExtra("body").orEmpty()
        val nid = intent.getIntExtra("nid", session.hashCode())
        val operation = "$base\u0000$session"
        if (!pending.add(operation)) return

        val result = goAsync()
        thread {
            val ok = runCatching {
                val host = java.net.URI(base).host ?: error("Missing host")
                val cookie = CookieManager.getInstance().getCookie(base).orEmpty()
                check(cookie.isNotBlank()) { "Missing login cookie" }
                val tm = Tls.Pinned(ctx, host)
                val client = OkHttpClient.Builder()
                    .sslSocketFactory(Tls.sslContext(tm).socketFactory, tm)
                    .hostnameVerifier { h, _ -> h == host }
                    .callTimeout(8, TimeUnit.SECONDS)
                    .build()
                val requestBody = """{"keys":["$key"]}"""
                    .toRequestBody("application/json".toMediaType())
                val request = Request.Builder()
                    .url("$base/api/sessions/${java.net.URLEncoder.encode(session, "UTF-8")}/keys")
                    .header("Cookie", cookie)
                    .post(requestBody)
                    .build()
                client.newCall(request).execute().use { it.isSuccessful }
            }.getOrDefault(false)

            try {
                val manager = ctx.getSystemService(NotificationManager::class.java)
                if (ok) manager.cancel(nid) else postRetry(ctx, manager, base, session, title, body, nid)
            } finally {
                pending.remove(operation)
                result.finish()
            }
        }
    }

    private fun postRetry(
        ctx: Context,
        manager: NotificationManager,
        base: String,
        session: String,
        title: String,
        body: String,
        nid: Int,
    ) {
        val open = PendingIntent.getActivity(
            ctx,
            session.hashCode(),
            Intent(ctx, WebActivity::class.java)
                .putExtra("path", "/#/inbox/" + java.net.URLEncoder.encode(session, "UTF-8"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notification = NotificationCompat.Builder(ctx, EventService.CH_EVENTS)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle(title)
            .setContentText(ctx.getString(R.string.action_failed))
            .setStyle(NotificationCompat.BigTextStyle().bigText("${body.trim()}\n\n${ctx.getString(R.string.action_failed)}"))
            .setContentIntent(open)
            .setAutoCancel(false)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setRequestPromotedOngoing(true)
            .setShortCriticalText(ctx.getString(R.string.event_waiting_chip))

        for ((action, key) in listOf("allow" to "Enter", "deny" to "Escape")) {
            val retry = PendingIntent.getBroadcast(
                ctx,
                (session + action).hashCode(),
                Intent(ctx, ActionReceiver::class.java)
                    .putExtra("base", base)
                    .putExtra("session", session)
                    .putExtra("key", key)
                    .putExtra("nid", nid)
                    .putExtra("title", title)
                    .putExtra("body", body),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            notification.addAction(
                0,
                ctx.getString(if (action == "allow") R.string.act_allow else R.string.act_deny),
                retry,
            )
        }
        manager.notify(nid, notification.build())
    }

    companion object {
        private val pending = ConcurrentHashMap.newKeySet<String>()
    }
}
