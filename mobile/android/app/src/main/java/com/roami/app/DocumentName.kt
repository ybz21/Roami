package com.roami.app

import java.net.URI
import java.net.URLDecoder

internal object DocumentName {
    fun resolve(url: String, disposition: String?, mime: String?): String {
        val encoded = Regex("(?:^|;)\\s*filename\\*\\s*=\\s*([^;]+)", RegexOption.IGNORE_CASE)
            .find(disposition.orEmpty())?.groupValues?.get(1)?.trim()?.trim('"')
        val extended = encoded?.split('\'', limit = 3)?.takeIf { it.size == 3 }?.let {
            runCatching { URLDecoder.decode(it[2].replace("+", "%2B"), it[0]) }.getOrNull()
        }
        val quoted = Regex("(?:^|;)\\s*filename\\s*=\\s*\"((?:\\\\.|[^\"])*)\"", RegexOption.IGNORE_CASE)
            .find(disposition.orEmpty())?.groupValues?.get(1)?.replace(Regex("\\\\(.)"), "$1")
        val plain = Regex("(?:^|;)\\s*filename\\s*=\\s*([^;]+)", RegexOption.IGNORE_CASE)
            .find(disposition.orEmpty())?.groupValues?.get(1)?.trim()?.trim('"')
        val path = runCatching { URI(url).path.substringAfterLast('/') }.getOrNull()
        val name = (extended ?: quoted ?: plain ?: path).orEmpty().replace('\\', '/')
            .substringAfterLast('/').filter { !it.isISOControl() }.trim()
        val extension = when (mime?.substringBefore(';')?.trim()?.lowercase()) {
            "application/pdf" -> ".pdf"
            "application/vnd.openxmlformats-officedocument.presentationml.presentation" -> ".pptx"
            "application/vnd.ms-powerpoint" -> ".ppt"
            else -> ""
        }
        if (name.isBlank() || name in setOf(".", "..", "content")) return "document$extension"
        return if (extension.isNotEmpty() && !name.contains('.')) name + extension else name
    }
}
