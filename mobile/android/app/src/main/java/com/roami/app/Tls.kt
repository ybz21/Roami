package com.roami.app

import android.content.Context
import java.security.MessageDigest
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection

/** 自签证书的 TOFU：系统 / 用户 CA 认的直接过；不认的看叶子证书指纹是不是这台主机上信任过的那张。 */
object Tls {
    fun fingerprint(cert: X509Certificate): String =
        MessageDigest.getInstance("SHA-256").digest(cert.encoded).joinToString(":") { "%02X".format(it) }

    private fun systemTm(): X509TrustManager {
        val f = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
        f.init(null as java.security.KeyStore?)
        return f.trustManagers.first { it is X509TrustManager } as X509TrustManager
    }

    class Pinned(ctx: Context, private val host: String) : X509TrustManager {
        private val prefs = Prefs(ctx)
        private val sys = systemTm()
        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) = sys.checkClientTrusted(chain, authType)
        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
            try { sys.checkServerTrusted(chain, authType); return } catch (_: Exception) {}
            val fp = fingerprint(chain[0])
            if (prefs.trusted(host) != fp) throw java.security.cert.CertificateException("untrusted self-signed cert for $host")
        }
        override fun getAcceptedIssuers(): Array<X509Certificate> = sys.acceptedIssuers
    }

    fun sslContext(tm: X509TrustManager): SSLContext = SSLContext.getInstance("TLS").apply { init(null, arrayOf(tm), null) }

    fun hostnameVerifier(ctx: Context, host: String) = HostnameVerifier { name, session ->
        name.equals(host, ignoreCase = true) && (
            HttpsURLConnection.getDefaultHostnameVerifier().verify(name, session) ||
                runCatching {
                    val certificate = session.peerCertificates.first() as X509Certificate
                    Prefs(ctx).trusted(host) == fingerprint(certificate)
                }.getOrDefault(false)
            )
    }
}
