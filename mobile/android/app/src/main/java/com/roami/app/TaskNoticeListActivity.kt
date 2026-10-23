package com.roami.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.BaseAdapter
import android.widget.ListView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

class TaskNoticeListActivity : AppCompatActivity() {
    private lateinit var base: String
    private var tasks: List<CapsuleTask> = emptyList()
    private val changed = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.getStringExtra("base") == base) refresh()
        }
    }
    private val adapter = object : BaseAdapter() {
        override fun getCount() = tasks.size
        override fun getItem(position: Int) = tasks[position]
        override fun getItemId(position: Int) = position.toLong()
        override fun getView(position: Int, recycled: View?, parent: ViewGroup): View {
            val row = recycled ?: layoutInflater.inflate(R.layout.row_task_notice, parent, false)
            val task = getItem(position)
            val kind = task.attention()
            val status = getString(when (kind) {
                TaskAttention.COMPLETED -> R.string.event_finished_chip
                TaskAttention.APPROVAL -> R.string.event_waiting_chip
                TaskAttention.CHOICE, TaskAttention.MULTIPLE -> R.string.event_choice_chip
                TaskAttention.INPUT -> R.string.event_input_chip
                TaskAttention.FAILED -> R.string.event_failed_chip
            })
            row.findViewById<TextView>(R.id.task_status).apply {
                text = status
                setTextColor(ContextCompat.getColor(this@TaskNoticeListActivity, when (task.state) {
                    TaskNoticeState.WAITING -> R.color.task_warning
                    TaskNoticeState.FINISHED -> R.color.task_success
                    TaskNoticeState.FAILED -> R.color.task_error
                }))
            }
            row.findViewById<TextView>(R.id.task_name).text = TaskNotificationText.taskName(task.title, task.session) ?: status
            row.findViewById<TextView>(R.id.task_summary).text = TaskNotificationText.summary(if (task.state == TaskNoticeState.WAITING)
                task.body.lineSequence().firstOrNull { it.isNotBlank() }.orEmpty() else task.body)
            return row
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        base = intent.getStringExtra("base") ?: Prefs(this).current ?: run { finish(); return }
        if (!ServerOrigin.matches(base, base)) { finish(); return }
        setContentView(R.layout.activity_task_notices)
        findViewById<View>(R.id.task_back).setOnClickListener { finish() }
        findViewById<ListView>(R.id.task_list).apply {
            adapter = this@TaskNoticeListActivity.adapter
            emptyView = this@TaskNoticeListActivity.findViewById(R.id.task_empty)
            setOnItemClickListener { _, _, position, _ ->
                tasks.getOrNull(position)?.let { startActivity(TaskNotification.chatIntent(this@TaskNoticeListActivity, base, it.session)) }
            }
        }
        ContextCompat.startForegroundService(this, Intent(this, EventService::class.java).putExtra("base", base))
    }

    override fun onStart() {
        super.onStart()
        if (!::base.isInitialized || isFinishing) return
        ContextCompat.registerReceiver(this, changed, IntentFilter(EventService.ACTION_TASK_CARDS_CHANGED), ContextCompat.RECEIVER_NOT_EXPORTED)
        refresh()
    }

    override fun onStop() {
        if (::base.isInitialized) runCatching { unregisterReceiver(changed) }
        super.onStop()
    }

    private fun refresh() {
        tasks = Prefs(this).taskCards(base)
        adapter.notifyDataSetChanged()
    }
}
