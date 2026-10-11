package com.roami.app

import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.webkit.CookieManager
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.IOException
import java.net.URI
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import kotlin.concurrent.thread

/** Download updates through the app's pinned TLS trust, then hand the APK to Android's installer. */
class ApkUpdate(private val activity: AppCompatActivity, private val base: String) {
    private var busy = false
    private var pending: Uri? = null

    fun download(url: String) {
        if (busy || !ServerOrigin.matches(base, url) || URI(url).path != "/api/apk") return
        busy = true
        Toast.makeText(activity, R.string.update_downloading, Toast.LENGTH_SHORT).show()
        val cookie = CookieManager.getInstance().getCookie(url)
        thread {
            val result = runCatching {
                val host = URI(base).host ?: throw IOException("Invalid server")
                val client = OkHttpClient.Builder().apply {
                    if (URI(base).scheme == "https") {
                        val tm = Tls.Pinned(activity, host)
                        sslSocketFactory(Tls.sslContext(tm).socketFactory, tm)
                        hostnameVerifier { name, _ -> name == host }
                    }
                }.build()
                val request = Request.Builder().url(url).apply {
                    if (!cookie.isNullOrBlank()) header("Cookie", cookie)
                }.build()
                val dir = File(activity.cacheDir, "updates").apply { mkdirs() }
                val tmp = File(dir, "roami.apk.part")
                client.newCall(request).execute().use { response ->
                    if (!response.isSuccessful || !response.header("Content-Type", "").orEmpty().startsWith("application/vnd.android.package-archive"))
                        throw IOException(activity.getString(R.string.update_bad_response))
                    val body = response.body ?: throw IOException(activity.getString(R.string.update_bad_response))
                    body.byteStream().use { input -> tmp.outputStream().use { output -> input.copyTo(output) } }
                }
                if (tmp.length() == 0L) throw IOException(activity.getString(R.string.update_bad_response))
                val apk = File(dir, "roami.apk")
                Files.move(tmp.toPath(), apk.toPath(), StandardCopyOption.REPLACE_EXISTING)
                FileProvider.getUriForFile(activity, "${activity.packageName}.files", apk)
            }
            activity.runOnUiThread {
                busy = false
                result.onSuccess { pending = it; installIfAllowed() }
                    .onFailure { Toast.makeText(activity, activity.getString(R.string.update_failed, it.message ?: ""), Toast.LENGTH_LONG).show() }
            }
        }
    }

    fun installIfAllowed() {
        val uri = pending ?: return
        if (Build.VERSION.SDK_INT >= 26 && !activity.packageManager.canRequestPackageInstalls()) {
            activity.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:${activity.packageName}")))
            return
        }
        pending = null
        val intent = Intent(Intent.ACTION_INSTALL_PACKAGE).apply {
            data = uri
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        @Suppress("DEPRECATION")
        val installers = activity.packageManager.queryIntentActivities(intent, PackageManager.MATCH_DEFAULT_ONLY)
        installers.firstOrNull { info ->
            info.activityInfo.packageName.contains("packageinstaller") &&
                info.activityInfo.applicationInfo.flags and ApplicationInfo.FLAG_SYSTEM != 0
        }?.let { intent.setClassName(it.activityInfo.packageName, it.activityInfo.name) }
        activity.startActivity(intent)
    }

    fun onResume() {
        if (Build.VERSION.SDK_INT < 26 || activity.packageManager.canRequestPackageInstalls()) installIfAllowed()
    }
}
