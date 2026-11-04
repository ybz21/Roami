package com.roami.capsulesmoke;

import android.Manifest;
import android.app.Activity;
import android.app.Notification;
import android.app.NotificationManager;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.service.notification.StatusBarNotification;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class SmokeActivity extends Activity {
    private static final int NOTIFICATION_PERMISSION_REQUEST = 1;
    private TextView diagnostics;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int padding = (int) (24 * getResources().getDisplayMetrics().density);
        layout.setPadding(padding, padding, padding, padding);
        layout.setOnApplyWindowInsetsListener((view, insets) -> {
            android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
            view.setPadding(padding + bars.left, padding + bars.top,
                    padding + bars.right, padding + bars.bottom);
            return insets;
        });

        TextView instructions = new TextView(this);
        instructions.setText(R.string.instructions);
        layout.addView(instructions);

        Button start = new Button(this);
        start.setText(R.string.start);
        start.setOnClickListener(v -> startTest());
        layout.addView(start);

        Button stop = new Button(this);
        stop.setText(R.string.stop);
        stop.setOnClickListener(v -> startService(new Intent(this, CapsuleService.class).setAction(CapsuleService.ACTION_STOP)));
        layout.addView(stop);

        Button settings = new Button(this);
        settings.setText(R.string.promotion_settings);
        settings.setOnClickListener(v -> openPromotionSettings());
        layout.addView(settings);

        diagnostics = new TextView(this);
        layout.addView(diagnostics);
        setContentView(layout);
    }

    @Override protected void onResume() {
        super.onResume();
        refreshDiagnostics();
    }

    private void startTest() {
        if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, NOTIFICATION_PERMISSION_REQUEST);
            return;
        }
        startForegroundService(new Intent(this, CapsuleService.class).setAction(CapsuleService.ACTION_START));
        diagnostics.postDelayed(this::refreshDiagnostics, 500);
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode == NOTIFICATION_PERMISSION_REQUEST && results.length > 0
                && results[0] == PackageManager.PERMISSION_GRANTED) {
            startTest();
        } else {
            diagnostics.setText(R.string.permission_missing);
        }
    }

    private void refreshDiagnostics() {
        CapsuleService.ensureChannel(this);
        NotificationManager manager = getSystemService(NotificationManager.class);
        Notification candidate = CapsuleService.makeNotification(this);
        String promotion = getString(R.string.not_started);
        for (StatusBarNotification posted : manager.getActiveNotifications()) {
            if (posted.getId() == CapsuleService.NOTIFICATION_ID) {
                promotion = getString((posted.getNotification().flags & Notification.FLAG_PROMOTED_ONGOING) != 0
                        ? R.string.yes : R.string.no);
                break;
            }
        }
        diagnostics.setText(getString(R.string.diagnostics, Build.VERSION.SDK_INT,
                Build.MANUFACTURER + " " + Build.MODEL,
                getString(checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED ? R.string.yes : R.string.no),
                getString(manager.canPostPromotedNotifications() ? R.string.yes : R.string.no),
                getString(candidate.hasPromotableCharacteristics() ? R.string.yes : R.string.no), promotion));
    }

    private void openPromotionSettings() {
        Intent promotion = new Intent(Settings.ACTION_APP_NOTIFICATION_PROMOTION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName());
        try {
            startActivity(promotion);
        } catch (ActivityNotFoundException ignored) {
            startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName()));
        }
    }
}
