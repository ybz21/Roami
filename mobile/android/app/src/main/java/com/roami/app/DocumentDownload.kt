package com.roami.app

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import android.util.Log
import android.webkit.CookieManager
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException
import java.net.URI
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/** Save authenticated documents with the same TLS trust as the WebView. */
class DocumentDownload(
    private val activity: AppCompatActivity,
    private val base: String,
    private val chooseDestination: (Intent) -> Unit,
) {
    private data class Pending(val url: String, val agent: String, val name: String, val mime: String)
    private var pending: Pending? = null
    private var downloading = false
    private class SessionExpired : IOException()

    fun start(url: String, agent: String?, disposition: String?, mime: String?) {
        if (pending != null || downloading) {
            Toast.makeText(activity, R.string.document_busy, Toast.LENGTH_SHORT).show()
            return
        }
        if (!ServerOrigin.matches(base, url)) return
        val type = mime?.substringBefore(';')?.trim()?.takeIf { it.contains('/') } ?: "application/octet-stream"
        val request = Pending(url, agent.orEmpty(), DocumentName.resolve(url, disposition, type), type)
        pending = request
        runCatching {
            chooseDestination(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                this.type = request.mime
                putExtra(Intent.EXTRA_TITLE, request.name)
            })
        }.onFailure {
            pending = null
            Log.w("RoamiDocument", "Cannot open document destination", it)
            Toast.makeText(activity, R.string.document_failed, Toast.LENGTH_LONG).show()
        }
    }

    fun save(resultCode: Int, destination: Uri?) {
        val request = pending ?: return
        pending = null
        if (resultCode != Activity.RESULT_OK || destination == null) return
        downloading = true
        val cookie = CookieManager.getInstance().getCookie(request.url)
        Toast.makeText(activity, R.string.document_downloading, Toast.LENGTH_SHORT).show()
        thread(name = "roami-document-download") {
            val result = runCatching {
                val host = URI(base).host ?: throw IOException("Invalid server")
                val client = OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
                    .callTimeout(5, TimeUnit.MINUTES).apply {
                        if (URI(base).scheme == "https") {
                            val trust = Tls.Pinned(activity, host)
                            sslSocketFactory(Tls.sslContext(trust).socketFactory, trust)
                            hostnameVerifier(Tls.hostnameVerifier(activity, host))
                        }
                    }.build()
                try {
                    var url = request.url
                    for (redirect in 0..5) {
                        if (!ServerOrigin.matches(base, url)) throw IOException("Cross-origin download")
                        val call = Request.Builder().url(url).header("User-Agent", request.agent).apply {
                            if (!cookie.isNullOrBlank()) header("Cookie", cookie)
                        }.build()
                        client.newCall(call).execute().use { response ->
                            if (response.isRedirect) {
                                val next = response.header("Location") ?: throw IOException("Missing redirect")
                                url = response.request.url.resolve(next)?.toString() ?: throw IOException("Invalid redirect")
                            } else {
                                if (response.code == 401) throw SessionExpired()
                                if (!response.isSuccessful) throw IOException("HTTP ${response.code}")
                                val body = response.body ?: throw IOException("Empty response")
                                if (body.contentType()?.subtype == "html" && request.mime != "text/html")
                                    throw SessionExpired()
                                activity.contentResolver.openOutputStream(destination, "w").use { output ->
                                    if (output == null) throw IOException("Cannot save document")
                                    body.byteStream().use { input ->
                                        val copied = input.copyTo(output)
                                        if (body.contentLength() >= 0 && copied != body.contentLength())
                                            throw IOException("Incomplete download")
                                    }
                                }
                                return@runCatching
                            }
                        }
                    }
                    throw IOException("Too many redirects")
                } finally {
                    client.dispatcher.executorService.shutdown()
                    client.connectionPool.evictAll()
                }
            }
            if (result.isFailure) {
                runCatching { DocumentsContract.deleteDocument(activity.contentResolver, destination) }
                Log.w("RoamiDocument", "Document download failed", result.exceptionOrNull())
            }
            activity.runOnUiThread {
                downloading = false
                if (!activity.isFinishing && !activity.isDestroyed) {
                    val message = if (result.isSuccess) activity.getString(R.string.document_saved, request.name)
                        else activity.getString(if (result.exceptionOrNull() is SessionExpired) R.string.document_login else R.string.document_failed)
                    Toast.makeText(activity, message, Toast.LENGTH_LONG).show()
                }
            }
        }
    }
}
