package com.roami.app

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.core.content.ContextCompat
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/** WebView 音频源不可用时，直接用 Android 的录音设备录制并交给现有识别接口。 */
internal class NativeVoiceInput(
    private val context: Context,
    private val base: String,
    private val cookie: () -> String?,
    private val onResult: (String, String?) -> Unit,
) {
    private val lock = Any()
    private var recorder: AudioRecord? = null
    @Volatile private var recording = false
    @Volatile private var canceled = false
    private val rate = 16_000

    fun start(nodeId: String): String = synchronized(lock) {
        if (recorder != null) return@synchronized "busy"
        if (!Regex("[A-Za-z0-9_-]{0,128}").matches(nodeId)) return@synchronized "invalid-node"
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
            return@synchronized "permission"
        val min = AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        if (min <= 0) return@synchronized "unavailable"
        val audio = try {
            AudioRecord.Builder()
                .setAudioSource(MediaRecorder.AudioSource.MIC)
                .setAudioFormat(AudioFormat.Builder().setSampleRate(rate)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setChannelMask(AudioFormat.CHANNEL_IN_MONO).build())
                .setBufferSizeInBytes(maxOf(min * 2, 4096)).build()
        } catch (_: Exception) { return@synchronized "unavailable" }
        if (audio.state != AudioRecord.STATE_INITIALIZED) { audio.release(); return@synchronized "unavailable" }
        try { audio.startRecording() } catch (_: Exception) { audio.release(); return@synchronized "unavailable" }
        if (audio.recordingState != AudioRecord.RECORDSTATE_RECORDING) { audio.release(); return@synchronized "unavailable" }
        recorder = audio
        val pcm = ByteArrayOutputStream()
        canceled = false
        recording = true
        thread(name = "roami-voice-capture") {
            val buf = ByteArray(maxOf(min, 4096))
            var failed = false
            while (recording) {
                val n = audio.read(buf, 0, buf.size)
                if (n > 0) {
                    pcm.write(buf, 0, n)
                    if (pcm.size() >= rate * 2 * 300) recording = false
                }
                else if (n < 0) { failed = true; break }
            }
            runCatching { audio.stop() }
            audio.release()
            synchronized(lock) { recorder = null; recording = false }
            if (canceled) return@thread
            if (failed) { onResult("error", "unavailable"); return@thread }
            val bytes = pcm.toByteArray()
            if (bytes.size < rate) { onResult("short", null); return@thread }
            try { onResult("success", transcribe(encodePcmWav(bytes, rate), nodeId)) }
            catch (e: Exception) { onResult("error", e.message ?: "transcription") }
        }
        "recording"
    }

    fun stop(cancel: Boolean): String = synchronized(lock) {
        if (!recording) return@synchronized "idle"
        canceled = cancel
        recording = false
        "stopping"
    }

    fun close() { stop(true) }

    private fun transcribe(wav: ByteArray, nodeId: String): String {
        val host = java.net.URI(base).host ?: error("server")
        val tm = Tls.Pinned(context, host)
        val client = OkHttpClient.Builder()
            .sslSocketFactory(Tls.sslContext(tm).socketFactory, tm)
            .hostnameVerifier { h, _ -> h == host }
            .callTimeout(2, TimeUnit.MINUTES).build()
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("audio", "audio.wav", wav.toRequestBody("audio/wav".toMediaType())).build()
        val route = if (nodeId.isEmpty()) "/api/speech/transcribe" else "/n/$nodeId/api/speech/transcribe"
        val request = Request.Builder().url("$base$route")
            .header("Cookie", cookie() ?: "").post(body).build()
        client.newCall(request).execute().use { response ->
            val json = JSONObject(response.body?.string() ?: "{}")
            if (!response.isSuccessful) {
                val reason = json.optJSONObject("error")?.let { it.optString("message").ifBlank { it.optString("code") } }
                error(reason?.ifBlank { "HTTP ${response.code}" } ?: "HTTP ${response.code}")
            }
            return json.optJSONObject("data")?.optString("text") ?: ""
        }
    }
}

internal fun encodePcmWav(bytes: ByteArray, rate: Int): ByteArray {
    val out = ByteArrayOutputStream(44 + bytes.size)
    fun str(value: String) = out.write(value.toByteArray(Charsets.US_ASCII))
    fun le(value: Int, count: Int) { repeat(count) { out.write(value ushr (it * 8) and 0xff) } }
    str("RIFF"); le(bytes.size + 36, 4); str("WAVEfmt ")
    le(16, 4); le(1, 2); le(1, 2); le(rate, 4); le(rate * 2, 4)
    le(2, 2); le(16, 2); str("data"); le(bytes.size, 4); out.write(bytes)
    return out.toByteArray()
}
