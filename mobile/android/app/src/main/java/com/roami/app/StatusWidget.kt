package com.roami.app

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import android.view.View
import android.widget.RemoteViews
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

data class WidgetSession(val name: String, val label: String, val project: String)

data class WidgetSnapshot(val running: Int, val waiting: Int, val runningItems: List<WidgetSession>,
    val waitingItem: WidgetSession?, val updated: Long) {
    companion object {
        fun fromOverview(items: JSONArray): WidgetSnapshot {
            var running = 0
            var waiting = 0
            val runningItems = mutableListOf<WidgetSession>()
            var waitingItem: WidgetSession? = null
            for (i in 0 until items.length()) {
                val item = items.optJSONObject(i) ?: continue
                val session = WidgetSession(item.optString("name"), item.optString("label"), item.optString("project"))
                if (item.optBoolean("waiting")) { waiting++; if (waitingItem == null) waitingItem = session }
                if (item.optBoolean("running")) { running++; if (runningItems.size < 3) runningItems += session }
            }
            return WidgetSnapshot(running, waiting, runningItems, waitingItem, System.currentTimeMillis())
        }

        fun read(ctx: Context, base: String?): WidgetSnapshot? = runCatching {
            val sp = ctx.getSharedPreferences("widget", Context.MODE_PRIVATE)
            if (base == null || sp.getString("base", null) != base) return null
            val o = JSONObject(sp.getString("snapshot", "") ?: "")
            fun item(key: String): WidgetSession? = o.optJSONObject(key)?.let {
                WidgetSession(it.optString("name"), it.optString("label"), it.optString("project"))
            }
            val rows = o.optJSONArray("runningItems") ?: JSONArray()
            val runningItems = (0 until rows.length()).mapNotNull { rows.optJSONObject(it)?.let { row ->
                WidgetSession(row.optString("name"), row.optString("label"), row.optString("project"))
            } }
            WidgetSnapshot(o.optInt("running"), o.optInt("waiting"), runningItems, item("waitingItem"), o.optLong("updated"))
        }.getOrNull()
    }

    fun save(ctx: Context, base: String) {
        fun item(s: WidgetSession?) = s?.let { JSONObject().put("name", it.name).put("label", it.label).put("project", it.project) }
        val o = JSONObject().put("running", running).put("waiting", waiting).put("updated", updated)
            .put("runningItems", JSONArray().apply { runningItems.forEach { put(item(it)) } })
            .put("waitingItem", item(waitingItem))
        ctx.getSharedPreferences("widget", Context.MODE_PRIVATE).edit()
            .putString("base", base).putString("snapshot", o.toString()).apply()
    }
}

class StatusWidget : AppWidgetProvider() {
    override fun onUpdate(ctx: Context, manager: AppWidgetManager, ids: IntArray) {
        ids.forEach { manager.updateAppWidget(it, views(ctx)) }
    }

    override fun onReceive(ctx: Context, intent: Intent) {
        super.onReceive(ctx, intent)
        if (intent.action == ACTION_REFRESH) {
            val service = Intent(ctx, EventService::class.java).setAction(EventService.ACTION_REFRESH)
            if (Build.VERSION.SDK_INT >= 26) ctx.startForegroundService(service) else ctx.startService(service)
        }
    }

    companion object {
        private const val ACTION_REFRESH = "com.roami.app.REFRESH_WIDGET"

        fun update(ctx: Context) {
            val manager = AppWidgetManager.getInstance(ctx)
            val ids = manager.getAppWidgetIds(ComponentName(ctx, StatusWidget::class.java))
            ids.forEach { manager.updateAppWidget(it, views(ctx)) }
        }

        private fun open(ctx: Context, path: String, request: Int): PendingIntent =
            PendingIntent.getActivity(ctx, request, Intent(ctx, WebActivity::class.java).putExtra("path", path),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

        private fun views(ctx: Context): RemoteViews {
            val snap = WidgetSnapshot.read(ctx, Prefs(ctx).current)
            val view = RemoteViews(ctx.packageName, R.layout.widget_status)
            view.setTextViewText(R.id.widget_running_count, ctx.getString(R.string.widget_running_count, snap?.running ?: 0))
            view.setTextViewText(R.id.widget_waiting_count, ctx.getString(R.string.widget_waiting_count, snap?.waiting ?: 0))
            view.setTextColor(R.id.widget_waiting_count, ContextCompat.getColor(ctx,
                if ((snap?.waiting ?: 0) > 0) R.color.widget_attention else R.color.widget_muted))
            val time = snap?.updated?.let { SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(it)) }
            view.setTextViewText(R.id.widget_updated, time?.let { ctx.getString(R.string.widget_updated, it) } ?: ctx.getString(R.string.widget_not_connected))
            view.setOnClickPendingIntent(R.id.widget_root, open(ctx, "/#/projects", 410))
            val refresh = PendingIntent.getBroadcast(ctx, 411, Intent(ctx, StatusWidget::class.java).setAction(ACTION_REFRESH),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            view.setOnClickPendingIntent(R.id.widget_updated, refresh)
            val waiting = snap?.waitingItem
            view.setTextViewText(R.id.widget_waiting_item, if (waiting == null) ctx.getString(R.string.widget_no_waiting)
                else ctx.getString(R.string.widget_waiting_item, waiting.project.ifBlank { ctx.getString(R.string.widget_no_project) }, waiting.label))
            view.setTextColor(R.id.widget_waiting_item, ContextCompat.getColor(ctx,
                if (waiting != null) R.color.widget_foreground else R.color.widget_muted))
            if (waiting != null) {
                view.setOnClickPendingIntent(R.id.widget_waiting_item, open(ctx, "/#/inbox/" + java.net.URLEncoder.encode(waiting.name, "UTF-8"), 412))
            }
            val ids = intArrayOf(R.id.widget_running_item, R.id.widget_running_item_2, R.id.widget_running_item_3)
            ids.forEachIndexed { index, id ->
                val session = snap?.runningItems?.getOrNull(index)
                view.setViewVisibility(id, if (session != null || index == 0 && snap?.running == 0) View.VISIBLE else View.GONE)
                view.setTextViewText(id, if (session == null) ctx.getString(R.string.widget_empty)
                    else ctx.getString(R.string.widget_running_item, session.project.ifBlank { ctx.getString(R.string.widget_no_project) }, session.label))
                if (session != null) view.setOnClickPendingIntent(id,
                    open(ctx, "/#/inbox/" + java.net.URLEncoder.encode(session.name, "UTF-8"), 413 + index))
            }
            return view
        }
    }
}
