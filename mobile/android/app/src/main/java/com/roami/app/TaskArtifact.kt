package com.roami.app

import java.net.URI

data class TaskArtifact(val path: String) {
    companion object {
        fun fromBody(base: String, body: String): TaskArtifact? {
            val links = Regex("(?<!!)\\[[^]\\n]*]\\(([^)\\n]+)\\)").findAll(body)
            return links.mapNotNull { safePath(base, it.groupValues[1].trim().removeSurrounding("<", ">")) }
                .firstOrNull()?.let(::TaskArtifact)
        }

        private fun safePath(base: String, link: String): String? = runCatching {
            if (link.startsWith("//") || link.any { it == '\r' || it == '\n' }) return@runCatching null
            val candidate = when {
                link.startsWith("/home/") || link.startsWith("/tmp/") -> {
                    val local = URI(link.replace(" ", "%20"))
                    URI(null, null, "/api/file/serve${local.path}", local.query, local.fragment)
                }
                else -> URI(link)
            }
            if (candidate.path.orEmpty().split('/').any { it == ".." }) return@runCatching null
            if (candidate.userInfo != null || candidate.rawAuthority != null && !ServerOrigin.matches(base, candidate.toString())) return@runCatching null
            if (candidate.isAbsolute && !ServerOrigin.matches(base, candidate.toString())) return@runCatching null
            if (!candidate.path.orEmpty().startsWith("/api/file/serve/") ||
                !Regex("(?i)\\.html?$").containsMatchIn(candidate.path.orEmpty())) return@runCatching null
            val normalized = URI(candidate.normalize().toASCIIString())
            if (!normalized.path.startsWith("/api/file/serve/")) return@runCatching null
            buildString {
                append(normalized.rawPath)
                normalized.rawQuery?.let { append('?').append(it) }
                normalized.rawFragment?.let { append('#').append(it) }
            }
        }.getOrNull()
    }
}
