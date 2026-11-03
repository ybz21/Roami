package com.roami.app

import android.app.Activity
import android.net.Uri
import android.provider.DocumentsContract
import android.webkit.CookieManager
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink
import okio.source
import org.json.JSONObject
import java.io.IOException
import java.net.URI
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

class FolderUpload(private val activity: Activity, private val base: String) {
    private data class Entry(val uri: Uri, val name: String, val path: String, val mime: String)

    fun upload(tree: Uri, targetDir: String, path: String, done: (Result<Int>) -> Unit) {
        val url = base.trimEnd('/') + path
        val cookie = CookieManager.getInstance().getCookie(url)
        thread {
            val result = runCatching {
                val entries = try { collect(tree) } catch (e: Exception) { throw IOException("FOLDER_READ_FAILED", e) }
                if (entries.isEmpty()) throw IOException("EMPTY_FOLDER")
                val body = MultipartBody.Builder().setType(MultipartBody.FORM).addFormDataPart("dir", targetDir)
                entries.forEach { entry ->
                    body.addFormDataPart("files", entry.name, object : RequestBody() {
                        override fun contentType() = entry.mime.toMediaTypeOrNull()
                        override fun writeTo(sink: BufferedSink) {
                            val input = try { activity.contentResolver.openInputStream(entry.uri) }
                                catch (e: Exception) { throw IOException("FOLDER_READ_FAILED", e) }
                                ?: throw IOException("FOLDER_READ_FAILED")
                            input.use { sink.writeAll(it.source()) }
                        }
                    })
                    body.addFormDataPart("paths", entry.path)
                }
                val host = URI(base).host ?: throw IOException("INVALID_UPLOAD_TARGET")
                val client = OkHttpClient.Builder().writeTimeout(10, TimeUnit.MINUTES).readTimeout(10, TimeUnit.MINUTES).apply {
                    if (URI(base).scheme == "https") {
                        val tm = Tls.Pinned(activity, host)
                        sslSocketFactory(Tls.sslContext(tm).socketFactory, tm)
                        hostnameVerifier { name, _ -> name == host }
                    }
                }.build()
                val request = Request.Builder().url(url).post(body.build()).apply {
                    if (!cookie.isNullOrBlank()) header("Cookie", cookie)
                }.build()
                client.newCall(request).execute().use { response ->
                    val payload = response.body?.string().orEmpty()
                    if (!response.isSuccessful) {
                        val error = runCatching { JSONObject(payload).optJSONObject("error")?.optString("message") }.getOrNull()
                        throw IOException(error?.takeIf { it.isNotBlank() } ?: "HTTP ${response.code}")
                    }
                    JSONObject(payload).getJSONObject("data").getJSONArray("saved").length()
                }
            }
            activity.runOnUiThread { done(result) }
        }
    }

    private fun collect(tree: Uri): List<Entry> {
        val resolver = activity.contentResolver
        val rootId = DocumentsContract.getTreeDocumentId(tree)
        val rootUri = DocumentsContract.buildDocumentUriUsingTree(tree, rootId)
        val rootName = resolver.query(rootUri, arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME), null, null, null)?.use {
            if (it.moveToFirst()) it.getString(0) else null
        } ?: throw IOException("FOLDER_READ_FAILED")
        val entries = mutableListOf<Entry>()

        fun segment(name: String) = name.replace('/', '_').replace('\\', '_').let {
            if (it == "." || it == "..") "_" else it
        }
        fun visit(parentId: String, path: String) {
            val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, parentId)
            val columns = arrayOf(
                DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                DocumentsContract.Document.COLUMN_MIME_TYPE,
            )
            val items: List<Triple<String, String, String?>> = resolver.query(children, columns, null, null, null)?.use { cursor ->
                val found = mutableListOf<Triple<String, String, String?>>()
                while (cursor.moveToNext()) found += Triple(cursor.getString(0), cursor.getString(1), cursor.getString(2))
                found
            } ?: throw IOException("FOLDER_READ_FAILED")
            for ((id, name, mime) in items) {
                val relative = "$path/${segment(name)}"
                if (mime == DocumentsContract.Document.MIME_TYPE_DIR) visit(id, relative)
                else entries += Entry(DocumentsContract.buildDocumentUriUsingTree(tree, id), name, relative, mime ?: "application/octet-stream")
            }
        }
        visit(rootId, segment(rootName))
        return entries
    }
}
