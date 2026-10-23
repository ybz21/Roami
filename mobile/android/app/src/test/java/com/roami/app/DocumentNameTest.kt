package com.roami.app

import org.junit.Assert.assertEquals
import org.junit.Test

class DocumentNameTest {
    @Test fun preservesUtf8ArtifactNamesAndLiteralPlus() {
        assertEquals("模块介绍+架构.pdf", DocumentName.resolve("https://roami.test/api/agent/artifacts/id/content",
            "attachment; filename*=utf-8''%E6%A8%A1%E5%9D%97%E4%BB%8B%E7%BB%8D+%E6%9E%B6%E6%9E%84.pdf", "application/pdf"))
    }

    @Test fun handlesQuotedNamesAndRejectsPathComponents() {
        assertEquals("report; final.pptx", DocumentName.resolve("https://roami.test/content",
            "attachment; filename=\"report; final.pptx\"", null))
        assertEquals("report.pdf", DocumentName.resolve("https://roami.test/content",
            "attachment; filename=\"../../report.pdf\"", "application/pdf"))
    }

    @Test fun fallsBackWhenExtendedHeaderIsMalformed() {
        assertEquals("report.pdf", DocumentName.resolve("https://roami.test/content",
            "attachment; filename*=UTF-8''%ZZ; filename=report.pdf", "application/pdf"))
        assertEquals("document.pdf", DocumentName.resolve("https://roami.test/api/artifacts/id/content", null, "application/pdf"))
    }
}
