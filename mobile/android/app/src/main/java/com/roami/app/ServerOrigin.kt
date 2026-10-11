package com.roami.app

import java.net.URI

internal object ServerOrigin {
    fun matches(server: String, candidate: String): Boolean = runCatching {
        val expected = URI(server)
        val actual = URI(candidate)
        val scheme = expected.scheme?.lowercase() ?: return@runCatching false
        if (scheme != "https" && scheme != "http") return@runCatching false
        val host = expected.host ?: return@runCatching false
        scheme == actual.scheme?.lowercase() &&
            host.equals(actual.host, ignoreCase = true) &&
            port(expected) == port(actual)
    }.getOrDefault(false)

    private fun port(uri: URI): Int = when {
        uri.port != -1 -> uri.port
        uri.scheme.equals("https", ignoreCase = true) -> 443
        uri.scheme.equals("http", ignoreCase = true) -> 80
        else -> -1
    }
}
