package com.roami.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TaskArtifactTest {
    private val base = "https://192.168.130.55:13579"

    @Test fun opensSameServerHtmlWithVersionAndSection() {
        assertEquals("/api/file/serve/home/project/index.html?v=2#result", TaskArtifact.fromBody(base,
            "[预览]($base/api/file/serve/home/project/index.html?v=2#result)")?.path)
    }

    @Test fun convertsLocalFileAndEscapesSpacesAndUnicode() {
        assertEquals("/api/file/serve/home/project/a%20b/%E9%A1%B5%E9%9D%A2.html#result", TaskArtifact.fromBody(base,
            "[预览](</home/project/a b/页面.html#result>)")?.path)
    }

    @Test fun doesNotTreatUnrelatedDownloadsAndForeignPagesAsPreview() {
        for (url in listOf("/api/apk", "https://evil.test/api/file/serve/home/a.html", "//evil.test/api/file/serve/a.html",
            "javascript:alert(1)", "$base/api/file/serve/%2e%2e/a.html", "$base/api/file/serve/../../a.html", "https://u:p@192.168.130.55:13579/api/file/serve/a.html")) {
            assertNull(url, TaskArtifact.fromBody(base, "[结果]($url)"))
        }
    }

    @Test fun selectsFirstSafeArtifactAndIgnoresEmbeddedImages() {
        assertEquals("/api/file/serve/tmp/result.html", TaskArtifact.fromBody(base,
            "[外链](https://other.test/a.html) ![截图](/api/file/serve/tmp/image.html) [结果](/api/file/serve/tmp/result.html)")?.path)
    }
}
