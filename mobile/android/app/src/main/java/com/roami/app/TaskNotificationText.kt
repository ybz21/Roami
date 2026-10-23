package com.roami.app

object TaskNotificationText {
    private fun terminalText(text: String): String = text
        .replace(Regex("\u001B\\][^\u0007\u001B]*(?:\u0007|\u001B\\\\)"), "")
        .replace(Regex("\u001B\\[[0-?]*[ -/]*[@-~]"), "")
        .replace(Regex("[\\p{Cc}&&[^\\n\\t]]"), "")

    fun plainText(text: String): String = terminalText(text)
        .replace(Regex("!?(\\[[^]\\n]+])\\([^\\n)]*\\)")) { it.groupValues[1].removeSurrounding("[", "]") }
        .replace(Regex("(?m)^\\s*```[^\\n]*$"), "")
        .replace(Regex("`([^`\\n]+)`"), "$1")
        .replace(Regex("\\*\\*([^*]+)\\*\\*"), "$1")
        .replace(Regex("(?m)^\\s*(?:#{1,6}\\s+|[-*]\\s+)"), "")
        .trim()

    fun summary(text: String): String {
        val clean = plainText(text).replace(Regex("\\s+"), " ")
        val sentences = clean.split(Regex("(?<=[。！？])|(?<=[.!?])\\s+")).map { it.trim() }.filter { it.isNotEmpty() }
        var result = sentences.firstOrNull().orEmpty().trim()
        if (result.codePointCount(0, result.length) < 12 && sentences.size > 1)
            result += " " + sentences[1].trim()
        return shorten(result, 60)
    }

    fun taskName(title: String, session: String): String? {
        val clean = plainText(title).replace(Regex("\\s+"), " ")
        if (clean.isBlank() || clean == session ||
            Regex("(?i)^(?:feat|fix|chore|docs|test|refactor|perf|build|ci|style)[/:_-].*").matches(clean) ||
            Regex("^\\d{4}-\\d{4}-.*").matches(clean)) return null
        return shorten(clean, 24)
    }

    fun resultDetails(body: String): String {
        val clean = plainText(body).replace(Regex("\\s+"), " ")
        val lead = summary(body)
        val unverified = clean.split(Regex("(?<=[。！？])|(?<=[.!?])\\s+"))
            .firstOrNull { Regex("(?i)(未|没有|待).{0,24}(验证|测试|验收)|not (?:yet )?(?:tested|verified)|unverified").containsMatchIn(it) }
            ?.trim()
        return if (unverified != null && !lead.contains(unverified)) "$lead\n${shorten(unverified, 100)}" else lead
    }

    fun questionDetails(body: String, choices: List<TaskChoice>): String {
        val clean = terminalText(body).trim()
        val missing = choices.filter { it.label.isNotBlank() && !clean.contains(terminalText(it.label)) }
        return (listOf(clean) + missing.map {
            (if (it.value.toIntOrNull() != null) "${it.value}. " else "") + terminalText(it.label)
        }).filter { it.isNotBlank() }.joinToString("\n")
    }

    private fun shorten(text: String, limit: Int): String {
        if (text.codePointCount(0, text.length) <= limit) return text
        return text.substring(0, text.offsetByCodePoints(0, limit)).trimEnd() + "…"
    }
}
