package com.roami.capsulesmoke;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

public final class CapsuleService extends Service {
    static final String ACTION_START = "com.roami.capsulesmoke.START";
    static final String ACTION_STOP = "com.roami.capsulesmoke.STOP";
    static final String CHANNEL_ID = "capsule_test";
    static final int NOTIFICATION_ID = 1;
    private static final long DURATION_MS = 120_000L;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable timeout = this::finishTest;

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || ACTION_STOP.equals(intent.getAction())) {
            finishTest();
            return START_NOT_STICKY;
        }
        ensureChannel(this);
        startForeground(NOTIFICATION_ID, makeNotification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_SHORT_SERVICE);
        handler.removeCallbacks(timeout);
        handler.postDelayed(timeout, DURATION_MS);
        return START_NOT_STICKY;
    }

    static void ensureChannel(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(
                CHANNEL_ID, context.getString(R.string.channel_name), NotificationManager.IMPORTANCE_DEFAULT));
    }

    static Notification makeNotification(Context context) {
        Intent open = new Intent(context, SmokeActivity.class);
        PendingIntent content = PendingIntent.getActivity(context, 0, open,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent stop = PendingIntent.getService(context, 1,
                new Intent(context, CapsuleService.class).setAction(ACTION_STOP),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification notification = new Notification.Builder(context, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_stat)
                .setContentTitle(context.getString(R.string.task_title))
                .setContentText(context.getString(R.string.task_body))
                .setStyle(new Notification.BigTextStyle().bigText(context.getString(R.string.task_body)))
                .setShortCriticalText(context.getString(R.string.chip_text))
                .setCategory(Notification.CATEGORY_PROGRESS)
                .setContentIntent(content)
                .addAction(new Notification.Action.Builder(
                        android.R.drawable.ic_menu_close_clear_cancel,
                        context.getString(R.string.stop), stop).build())
                .setOngoing(true)
                .build();
        // The public constant was added in API 36.1; Android 36 accepts the documented extras key.
        notification.extras.putBoolean("android.requestPromotedOngoing", true);
        return notification;
    }

    private Notification makeNotification() { return makeNotification(this); }

    private void finishTest() {
        handler.removeCallbacks(timeout);
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    @Override public void onDestroy() {
        handler.removeCallbacks(timeout);
        super.onDestroy();
    }
}
