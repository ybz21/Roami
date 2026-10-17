package com.roami.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.DownloadManager
import android.net.Uri
import android.os.Environment
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ApplicationInfo
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.view.View
import android.webkit.CookieManager
import android.webkit.PermissionRequest
import android.webkit.SslErrorHandler
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import java.security.cert.X509Certificate
import org.json.JSONObject

/** Roami WebView 容器：自签证书、系统键盘、摇一摇切环境与通知服务。 */
class WebActivity : AppCompatActivity() {
    private lateinit var web: WebView
    private lateinit var base: String
    private lateinit var shake: ShakeDetector
    private lateinit var apkUpdate: ApkUpdate
    private var askingSsl = false
    private var pendingAudio: PermissionRequest? = null
    private var lastImeHeight = -1
    private val micPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        val request = pendingAudio ?: return@registerForActivityResult
        pendingAudio = null
        if (granted && ServerOrigin.matches(base, request.origin.toString()))
            request.grant(arrayOf(PermissionRequest.RESOURCE_AUDIO_CAPTURE))
        else request.deny()
    }

    // 网页里的 <input type=file>（上传文件到工作目录、贴图）：WebView 默认什么都不做，得自己接系统选择器
    private var fileCb: ValueCallback<Array<Uri>>? = null
    private var folderTargetDir: String? = null
    private var folderUploadPath: String? = null
    private val pickFiles = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
        val cb = fileCb ?: return@registerForActivityResult
        fileCb = null
        val data = res.data
        val uris = mutableListOf<Uri>()
        if (res.resultCode == RESULT_OK && data != null) {
            data.clipData?.let { c -> for (i in 0 until c.itemCount) uris += c.getItemAt(i).uri }
            if (uris.isEmpty()) data.data?.let { uris += it }
        }
        cb.onReceiveValue(if (uris.isEmpty()) null else uris.toTypedArray())
    }
    private val pickFolder = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
        val dir = folderTargetDir ?: return@registerForActivityResult
        val path = folderUploadPath ?: return@registerForActivityResult
        folderTargetDir = null
        folderUploadPath = null
        val tree = if (res.resultCode == RESULT_OK) res.data?.data else null
        if (tree == null) {
            folderUploadResult(JSONObject().put("cancelled", true))
            return@registerForActivityResult
        }
        FolderUpload(this, base).upload(tree, dir, path) { result ->
            val detail = result.fold(
                { JSONObject().put("saved", it) },
                { JSONObject().put("error", it.message ?: "FOLDER_UPLOAD_FAILED") },
            )
            folderUploadResult(detail)
        }
    }

    private fun folderUploadResult(detail: JSONObject) {
        if (::web.isInitialized && !isFinishing && !isDestroyed)
            web.evaluateJavascript("window.dispatchEvent(new CustomEvent('roami-folder-upload', {detail: $detail}))", null)
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0) WebView.setWebContentsDebuggingEnabled(true)
        WindowCompat.setDecorFitsSystemWindows(window, true)
        base = intent.getStringExtra("url") ?: Prefs(this).current ?: run { finish(); return }
        apkUpdate = ApkUpdate(this, base)
        web = WebView(this)
        setContentView(web)
        // adjustNothing keeps the page stable; WebView does not expose its IME height to JS.
        ViewCompat.setOnApplyWindowInsetsListener(window.decorView) { _, insets ->
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime()).bottom
            val nav = insets.getInsets(WindowInsetsCompat.Type.navigationBars()).bottom
            val height = ((ime - nav).coerceAtLeast(0) / resources.displayMetrics.density).toInt()
            if (height != lastImeHeight) {
                lastImeHeight = height
                web.evaluateJavascript("window.__roamiNativeKeyboardHeight=$height;window.dispatchEvent(new Event('roami-keyboard'))", null)
            }
            insets
        }
        web.setBackgroundColor(0xFF0D1117.toInt())
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            mediaPlaybackRequiresUserGesture = false
            val ver = runCatching { packageManager.getPackageInfo(packageName, 0).versionName }.getOrNull() ?: "0"
            userAgentString = "$userAgentString RoamiApp/$ver"
            mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
        }
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true)
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, req: WebResourceRequest): Boolean {
                // 站内照常；外链交给系统浏览器
                if (!req.isForMainFrame) return false
                // WebView 不会把目录 URI 展开成 FileList，目录选择与上传须在 APK 内完成。
                if (req.url.scheme == "roami" && req.url.host == "folder-upload") {
                    val dir = req.url.getQueryParameter("dir")
                    val path = req.url.getQueryParameter("path")
                    if (!dir.isNullOrBlank() && dir.startsWith("/") &&
                        path != null && Regex("^/(?:n/[^/]+/)?api/upload$").matches(path) && folderTargetDir == null) {
                        folderTargetDir = dir
                        folderUploadPath = path
                        try { pickFolder.launch(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)) }
                        catch (e: Exception) {
                            folderTargetDir = null
                            folderUploadPath = null
                            folderUploadResult(JSONObject().put("error", "FOLDER_PICKER_UNAVAILABLE"))
                        }
                    } else folderUploadResult(JSONObject().put("error", "INVALID_UPLOAD_TARGET"))
                    return true
                }
                return if (ServerOrigin.matches(base, req.url.toString())) false
                    else { runCatching { startActivity(Intent(Intent.ACTION_VIEW, req.url)) }; true }
            }
            override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) {
                if (!ServerOrigin.matches(base, error.url)) { handler.cancel(); return }
                val cert = error.certificate?.x509Certificate
                val host = runCatching { java.net.URI(base).host }.getOrNull() ?: ""
                if (cert == null || host.isEmpty()) { handler.cancel(); return }
                val fp = Tls.fingerprint(cert)
                val prefs = Prefs(this@WebActivity)
                if (prefs.trusted(host) == fp) { handler.proceed(); return }
                if (askingSsl) { handler.cancel(); return }
                askingSsl = true
                AlertDialog.Builder(this@WebActivity)
                    .setTitle(R.string.ssl_title)
                    .setMessage(getString(R.string.ssl_body, host, fp))
                    .setPositiveButton(R.string.ssl_trust) { _, _ -> prefs.trust(host, fp); askingSsl = false; handler.proceed(); startEvents() }
                    .setNegativeButton(R.string.ssl_cancel) { _, _ -> askingSsl = false; handler.cancel(); finish() }
                    .setCancelable(false).show()
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest) {
                if (!ServerOrigin.matches(base, request.origin.toString()) ||
                    PermissionRequest.RESOURCE_AUDIO_CAPTURE !in request.resources) {
                    request.deny()
                    return
                }
                if (ContextCompat.checkSelfPermission(this@WebActivity, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                    request.grant(arrayOf(PermissionRequest.RESOURCE_AUDIO_CAPTURE))
                } else {
                    pendingAudio?.deny()
                    pendingAudio = request
                    micPermission.launch(Manifest.permission.RECORD_AUDIO)
                }
            }
            override fun onPermissionRequestCanceled(request: PermissionRequest) {
                if (pendingAudio === request) pendingAudio = null
            }
            override fun onShowFileChooser(view: WebView, cb: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                fileCb?.onReceiveValue(null) // 上一次没收尾的先还掉，不然页面那个 input 永远卡住
                fileCb = cb
                val i = Intent(Intent.ACTION_GET_CONTENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*")
                    .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.mode == FileChooserParams.MODE_OPEN_MULTIPLE)
                val types = params.acceptTypes.filter { it.isNotBlank() }
                if (types.size == 1) i.type = types[0] else if (types.size > 1) i.putExtra(Intent.EXTRA_MIME_TYPES, types.toTypedArray())
                return try { pickFiles.launch(Intent.createChooser(i, null)); true } catch (_: Exception) { fileCb = null; false }
            }
        }
        // APK 使用已信任的自签证书直接安装；其他文件仍交给系统下载管理器。
        web.setDownloadListener { url, ua, disposition, mime, _ ->
            if (ServerOrigin.matches(base, url) && Uri.parse(url).path == "/api/apk") {
                apkUpdate.download(url)
                return@setDownloadListener
            }
            runCatching {
                val name = URLUtil.guessFileName(url, disposition, mime)
                val req = DownloadManager.Request(Uri.parse(url))
                    .addRequestHeader("Cookie", CookieManager.getInstance().getCookie(url) ?: "")
                    .addRequestHeader("User-Agent", ua)
                    .setMimeType(mime).setTitle(name)
                    .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                    .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name)
                (getSystemService(DOWNLOAD_SERVICE) as DownloadManager).enqueue(req)
                Toast.makeText(this, name, Toast.LENGTH_SHORT).show()
            }.onFailure {
                // 自签证书下系统下载器会拒绝连接：退给浏览器去下
                runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
            }
        }
        val path = intent.getStringExtra("path") ?: ""
        web.loadUrl(base + path)

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                // 先让页面自己退（它的二级页 / 全屏会话都靠 history），退不动了才退 App
                if (web.canGoBack()) web.goBack() else { isEnabled = false; onBackPressedDispatcher.onBackPressed() }
            }
        })
        shake = ShakeDetector(this) {
            startActivity(Intent(this, PickActivity::class.java).putExtra("noauto", true).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP))
        }
        askPermissions()
        startEvents()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // 点通知进来：直接跳到那个会话
        intent.getStringExtra("path")?.let { web.loadUrl(base + it) }
    }

    private fun askPermissions() {
        val want = if (Build.VERSION.SDK_INT >= 33) listOf(Manifest.permission.POST_NOTIFICATIONS) else emptyList()
        val missing = want.filter { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) ActivityCompat.requestPermissions(this, missing.toTypedArray(), 1)
    }

    private fun startEvents() {
        val i = Intent(this, EventService::class.java).putExtra("base", base)
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(i) else startService(i)
    }

    override fun onResume() { super.onResume(); shake.start(); web.onResume(); apkUpdate.onResume() }
    override fun onPause() { super.onPause(); shake.stop(); web.onPause() }
    override fun onDestroy() {
        pendingAudio?.deny()
        pendingAudio = null
        super.onDestroy()
        if (::web.isInitialized) web.destroy()
    }
}
