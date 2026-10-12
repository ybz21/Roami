package com.roami.app

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.PowerManager
import android.view.View
import android.widget.RemoteViews
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

data class WidgetSession(val name: String, val label: String, val project: String)
data class WidgetRow(val session: WidgetSession, val waiting: Boolean)

data class WidgetSnapshot(val running: Int, val waiting: Int, val runningItems: List<WidgetSession>,
    val waitingItems: List<WidgetSession>, val updated: Long, val unfinished: Int = 0) {
    val attentionCount: Int get() = waiting + unfinished
    fun carouselRows(): List<WidgetRow> = if (runningItems.isNotEmpty())
        runningItems.map { WidgetRow(it, false) }
    else waitingItems.take(1).map { WidgetRow(it, true) }

    companion object {
        private const val MAX_AGE_MS = 60_000L

        fun fromOverview(items: JSONArray): WidgetSnapshot {
            var running = 0
            var waiting = 0
            val runningItems = mutableListOf<WidgetSession>()
            val waitingItems = mutableListOf<WidgetSession>()
            for (i in 0 until items.length()) {
                val item = items.optJSONObject(i) ?: continue
                val session = WidgetSession(item.optString("name"), item.optString("label"), item.optString("project"))
                if (item.optBoolean("waiting")) { waiting++; if (waitingItems.isEmpty()) waitingItems += session }
                if (item.optBoolean("running")) { running++; runningItems += session }
            }
            return WidgetSnapshot(running, waiting, runningItems, waitingItems, System.currentTimeMillis())
        }

        fun unfinishedFromProjects(projects: JSONArray): Int = (0 until projects.length()).sumOf { index ->
            projects.optJSONObject(index)?.optInt("unfinished")?.coerceAtLeast(0) ?: 0
        }

        fun read(ctx: Context, base: String?): WidgetSnapshot? = runCatching {
            val sp = ctx.getSharedPreferences("widget", Context.MODE_PRIVATE)
            if (base == null || sp.getString("base", null) != base) return null
            val o = JSONObject(sp.getString("snapshot", "") ?: "")
            fun items(key: String): List<WidgetSession> {
                val rows = o.optJSONArray(key) ?: JSONArray()
                return (0 until rows.length()).mapNotNull { rows.optJSONObject(it)?.let { row ->
                    WidgetSession(row.optString("name"), row.optString("label"), row.optString("project"))
                } }
            }
            val previousWaiting = o.optJSONObject("waitingItem")?.let {
                listOf(WidgetSession(it.optString("name"), it.optString("label"), it.optString("project")))
            } ?: emptyList()
            val updated = o.optLong("updated")
            if (updated <= 0 || System.currentTimeMillis() - updated !in 0..MAX_AGE_MS) return null
            WidgetSnapshot(o.optInt("running"), o.optInt("waiting"), items("runningItems"),
                o.optJSONArray("waitingItems")?.let { items("waitingItems") } ?: previousWaiting, updated,
                o.optInt("unfinished"))
        }.getOrNull()

        fun clear(ctx: Context): Boolean {
            val sp = ctx.getSharedPreferences("widget", Context.MODE_PRIVATE)
            if (!sp.contains("snapshot")) return false
            sp.edit().remove("snapshot").apply()
            return true
        }
    }

    fun save(ctx: Context, base: String) {
        fun items(list: List<WidgetSession>) = JSONArray().apply {
            list.forEach { put(JSONObject().put("name", it.name).put("label", it.label).put("project", it.project)) }
        }
        val o = JSONObject().put("running", running).put("waiting", waiting).put("unfinished", unfinished).put("updated", updated)
            .put("runningItems", items(runningItems)).put("waitingItems", items(waitingItems))
        ctx.getSharedPreferences("widget", Context.MODE_PRIVATE).edit()
            .putString("base", base).putString("snapshot", o.toString()).apply()
    }
}

class StatusWidget : AppWidgetProvider() {
    override fun onUpdate(ctx: Context, manager: AppWidgetManager, ids: IntArray) {
        ids.forEach { manager.updateAppWidget(it, views(ctx, it)) }
    }

    override fun onAppWidgetOptionsChanged(ctx: Context, manager: AppWidgetManager, id: Int, options: android.os.Bundle) {
        manager.updateAppWidget(id, views(ctx, id))
    }

    override fun onReceive(ctx: Context, intent: Intent) {
        super.onReceive(ctx, intent)
        if (intent.action == PowerManager.ACTION_POWER_SAVE_MODE_CHANGED) {
            update(ctx)
        } else if (intent.action == Intent.ACTION_MY_PACKAGE_REPLACED && Prefs(ctx).current != null) {
            ctx.startForegroundService(Intent(ctx, EventService::class.java))
        } else if (intent.action == ACTION_REFRESH) {
            val service = Intent(ctx, EventService::class.java).setAction(EventService.ACTION_REFRESH)
            if (Build.VERSION.SDK_INT >= 26) ctx.startForegroundService(service) else ctx.startService(service)
        }
    }

    companion object {
        private const val ACTION_REFRESH = "com.roami.app.REFRESH_WIDGET"
        private const val CAROUSEL_INTERVAL_MS = 10_000

        fun update(ctx: Context) {
            val manager = AppWidgetManager.getInstance(ctx)
            val ids = manager.getAppWidgetIds(ComponentName(ctx, StatusWidget::class.java))
            ids.forEach { manager.updateAppWidget(it, views(ctx, it)) }
        }

        private fun open(ctx: Context, path: String, request: Int): PendingIntent =
            PendingIntent.getActivity(ctx, request, Intent(ctx, WebActivity::class.java).putExtra("path", path),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

        private fun views(ctx: Context, widgetId: Int): RemoteViews {
            val snap = WidgetSnapshot.read(ctx, Prefs(ctx).current)
            val view = RemoteViews(ctx.packageName, R.layout.widget_status)
            view.setTextViewText(R.id.widget_running_count,
                if (snap == null) ctx.getString(R.string.widget_running_unavailable) else ctx.getString(R.string.widget_running_count, snap.running))
            view.setTextViewText(R.id.widget_waiting_count,
                if (snap == null) ctx.getString(R.string.widget_waiting_unavailable) else ctx.getString(R.string.widget_waiting_count, snap.attentionCount))
            view.setTextColor(R.id.widget_waiting_count, ContextCompat.getColor(ctx,
                if ((snap?.attentionCount ?: 0) > 0) R.color.widget_attention else R.color.widget_muted))
            val time = snap?.updated?.let { SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(it)) }
            view.setTextViewText(R.id.widget_updated, time?.let { ctx.getString(R.string.widget_updated, it) } ?: ctx.getString(R.string.widget_not_connected))
            view.setOnClickPendingIntent(R.id.widget_root, open(ctx, "/#/projects", widgetId * 10))
            val refresh = PendingIntent.getBroadcast(ctx, 411, Intent(ctx, StatusWidget::class.java).setAction(ACTION_REFRESH),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            view.setOnClickPendingIntent(R.id.widget_updated, refresh)
            val rows = snap?.carouselRows().orEmpty()
            view.removeAllViews(R.id.widget_session_flipper)
            val powerSave = ctx.getSystemService(PowerManager::class.java).isPowerSaveMode
            view.setInt(R.id.widget_session_flipper, "setFlipInterval",
                if (rows.size > 1 && !powerSave) CAROUSEL_INTERVAL_MS else Int.MAX_VALUE)
            rows.forEachIndexed { index, row ->
                val item = RemoteViews(ctx.packageName, R.layout.widget_session_row)
                item.setTextViewText(R.id.widget_session_state, ctx.getString(if (row.waiting) R.string.widget_state_waiting else R.string.widget_state_running))
                item.setTextColor(R.id.widget_session_state, ContextCompat.getColor(ctx,
                    if (row.waiting) R.color.widget_attention else R.color.widget_running))
                val project = row.session.project.ifBlank { ctx.getString(R.string.widget_no_project) }
                item.setTextViewText(R.id.widget_session_title, ctx.getString(R.string.widget_session, project, row.session.label))
                item.setTextViewText(R.id.widget_session_position,
                    if (rows.size > 1) ctx.getString(R.string.widget_position, index + 1, rows.size) else "")
                item.setOnClickPendingIntent(R.id.widget_session_row, open(ctx,
                    "/#/inbox/" + java.net.URLEncoder.encode(row.session.name, "UTF-8"), widgetId * 100 + index + 1))
                view.addView(R.id.widget_session_flipper, item)
            }
            view.setViewVisibility(R.id.widget_session_flipper, if (rows.isEmpty()) View.GONE else View.VISIBLE)
            view.setTextViewText(R.id.widget_empty, if (snap == null) ctx.getString(R.string.widget_not_connected)
                else ctx.getString(R.string.widget_empty))
            view.setViewVisibility(R.id.widget_empty, if (rows.isEmpty()) View.VISIBLE else View.GONE)
            view.setOnClickPendingIntent(R.id.widget_new_task, open(ctx, "/#/projects?compose=1", widgetId * 10 + 6))
            view.setOnClickPendingIntent(R.id.widget_sessions, open(ctx, "/#/projects", widgetId * 10 + 7))
            view.setOnClickPendingIntent(R.id.widget_waiting_action, open(ctx, "/#/projects?filter=waiting", widgetId * 10 + 8))
            return view
        }
    }
}
