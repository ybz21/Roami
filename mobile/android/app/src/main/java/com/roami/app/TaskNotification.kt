package com.roami.app

import android.app.Notification
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.graphics.drawable.Icon
import android.net.Uri
import java.net.URLEncoder

enum class TaskNoticeState { WAITING, FINISHED, FAILED }

object TaskNotification {
    fun id(session: String): Int = session.hashCode()
    fun tag(base: String): String = "task:$base"

    fun responseNotice(ctx: Context, base: String, session: String): Notification {
        val open = PendingIntent.getActivity(ctx, (base + session).hashCode(), chatIntent(ctx, base, session),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val public = Notification.Builder(ctx, EventService.CH_EVENTS).setSmallIcon(R.drawable.ic_stat)
            .setContentTitle(ctx.getString(R.string.event_response_title)).setContentIntent(open).build()
        return Notification.Builder(ctx, EventService.CH_EVENTS).setSmallIcon(R.drawable.ic_stat)
            .setContentTitle(ctx.getString(R.string.event_response_title))
            .setContentText(ctx.getString(R.string.event_prompt_changed)).setContentIntent(open)
            .setVisibility(Notification.VISIBILITY_PRIVATE).setPublicVersion(public).setAutoCancel(true).build()
    }

    fun chatIntent(ctx: Context, base: String, session: String): Intent = destination(ctx, base, session, "chat",
        "/#/inbox/" + URLEncoder.encode(session, "UTF-8"))

    private fun destination(ctx: Context, base: String, session: String, kind: String, path: String): Intent =
        Intent(ctx, WebActivity::class.java).putExtra("url", base).putExtra("path", path)
            .setData(Uri.Builder().scheme("roami").authority("notification").appendPath(kind)
                .appendQueryParameter("server", base).appendQueryParameter("session", session)
                .appendQueryParameter("target", path).build())
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

    fun build(ctx: Context, base: String, session: String, title: String, body: String,
              state: TaskNoticeState, actions: List<String> = emptyList(), retry: Boolean = false,
              capsule: Boolean = false, prompt: String = "", choices: List<TaskChoice> = emptyList(),
              selectionMode: String = "single", attentionCount: Int = 1): Notification {
        val open = PendingIntent.getActivity(ctx, (base + session).hashCode(),
            chatIntent(ctx, base, session),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val actionIcon = Icon.createWithResource(ctx, R.drawable.ic_stat)
        val live = capsule || state == TaskNoticeState.WAITING
        val kind = CapsuleTask(session, title, body, state, choices = choices, selectionMode = selectionMode).attention()
        val status = ctx.getString(when (kind) {
            TaskAttention.APPROVAL -> R.string.event_waiting_chip
            TaskAttention.CHOICE, TaskAttention.MULTIPLE -> R.string.event_choice_chip
            TaskAttention.INPUT -> R.string.event_input_chip
            TaskAttention.COMPLETED -> R.string.event_finished_chip
            TaskAttention.FAILED -> R.string.event_failed_chip
        })
        val fallback = ctx.getString(when (kind) {
            TaskAttention.APPROVAL -> R.string.event_waiting_title
            TaskAttention.CHOICE, TaskAttention.MULTIPLE -> R.string.event_choice_title
            TaskAttention.INPUT -> R.string.event_input_title
            TaskAttention.COMPLETED -> R.string.event_finished_title
            TaskAttention.FAILED -> R.string.event_failed_title
        })
        val renderedChoices = choices.map { it.copy(label = it.label(ctx)) }
        val content = when (state) {
            TaskNoticeState.FINISHED -> TaskNotificationText.resultDetails(body).ifBlank { ctx.getString(R.string.event_view_result) }
            TaskNoticeState.WAITING -> TaskNotificationText.questionDetails(body, renderedChoices)
            TaskNoticeState.FAILED -> TaskNotificationText.plainText(body)
        }
        val result = if (retry) ctx.getString(R.string.event_action_failed, content) else content
        val detail = if (attentionCount > 1) result + "\n" + ctx.getString(R.string.event_other_tasks, attentionCount - 1) else result
        val channel = if (capsule) EventService.CH_CAPSULE else EventService.CH_EVENTS
        val public = Notification.Builder(ctx, channel).setSmallIcon(R.drawable.ic_stat)
            .setContentTitle(fallback).setContentText(ctx.getString(R.string.event_unlock_details))
            .setContentIntent(open).setOngoing(live).build()
        val builder = Notification.Builder(ctx, channel)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle(TaskNotificationText.taskName(title, session) ?: fallback)
            .setSubText(status)
            .setContentText(TaskNotificationText.summary(if (state == TaskNoticeState.WAITING && !retry)
                result.lineSequence().firstOrNull { it.isNotBlank() }.orEmpty() else result))
            .setStyle(Notification.BigTextStyle().bigText(detail))
            .setContentIntent(open)
            .setVisibility(Notification.VISIBILITY_PRIVATE)
            .setPublicVersion(public)
            .setAutoCancel(!live)
            .setOngoing(live)
            .setOnlyAlertOnce(live && !retry)
            .setCategory(Notification.CATEGORY_PROGRESS)
            .setPriority(Notification.PRIORITY_HIGH)
        if (Build.VERSION.SDK_INT >= 29) builder.setAllowSystemGeneratedContextualActions(false)
        if (capsule && Build.VERSION.SDK_INT >= 36) builder.setShortCriticalText(
            if (attentionCount > 1) ctx.getString(R.string.event_pending_chip, attentionCount.coerceAtMost(99)) else status)
        var actionCount = 0
        if (state == TaskNoticeState.WAITING && prompt.isNotBlank() && kind != TaskAttention.MULTIPLE) for (choice in choices.take(if (choices.size > 3) 2 else 3)) {
            val respond = PendingIntent.getBroadcast(ctx, (base + session + prompt + choice.value).hashCode(),
                Intent(ctx, ActionReceiver::class.java)
                    .putExtra("base", base).putExtra("session", session)
                    .putExtra("prompt", prompt).putExtra("choice", choice.value)
                    .putExtra("title", title).putExtra("body", body)
                    .putExtra("selectionMode", selectionMode)
                    .putExtra("choices", TaskChoice.encode(choices)),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val action = Notification.Action.Builder(actionIcon, choice.label(ctx), respond)
            if (Build.VERSION.SDK_INT >= 31) action.setAuthenticationRequired(true)
            builder.addAction(action.build()); actionCount++
        }
        if (state == TaskNoticeState.WAITING && (choices.size > 3 || kind == TaskAttention.MULTIPLE || choices.isEmpty() || prompt.isBlank())) {
            builder.addAction(Notification.Action.Builder(actionIcon, ctx.getString(
                if (kind == TaskAttention.INPUT) R.string.event_open_input else R.string.event_all_choices), open).build())
            actionCount++
        }
        if (state == TaskNoticeState.FINISHED) TaskArtifact.fromBody(base, body)?.let { artifact ->
            val preview = PendingIntent.getActivity(ctx, (base + session + artifact.path).hashCode(),
                destination(ctx, base, session, "preview", artifact.path),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            builder.addAction(Notification.Action.Builder(actionIcon, ctx.getString(R.string.event_open_preview), preview).build())
            actionCount++
        }
        if (state == TaskNoticeState.FAILED) {
            builder.addAction(Notification.Action.Builder(actionIcon, ctx.getString(R.string.event_open_task), open).build())
            actionCount++
            val dismiss = PendingIntent.getBroadcast(ctx, (base + session + "dismiss").hashCode(),
                Intent(ctx, ActionReceiver::class.java).putExtra("base", base).putExtra("session", session).putExtra("dismiss", true),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            builder.addAction(Notification.Action.Builder(actionIcon, ctx.getString(R.string.event_acknowledge), dismiss).build())
            actionCount++
        }
        if (attentionCount > 1 && actionCount < 3) {
            val all = PendingIntent.getActivity(ctx, base.hashCode(),
                Intent(ctx, TaskNoticeListActivity::class.java).putExtra("base", base)
                    .setData(Uri.Builder().scheme("roami").authority("attention").appendQueryParameter("server", base).build()),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            builder.addAction(Notification.Action.Builder(actionIcon, ctx.getString(R.string.event_all_tasks), all).build())
        }
        val notification = builder.build()
        notification.extras.putString("roami.session", session)
        notification.extras.putString("roami.base", base)
        notification.extras.putString("roami.taskState", state.name)
        notification.extras.putString("roami.prompt", prompt)
        notification.extras.putString("roami.selectionMode", selectionMode)
        if (capsule && Build.VERSION.SDK_INT >= 36) {
            notification.extras.putBoolean("android.requestPromotedOngoing", true)
        }
        return notification
    }
}
