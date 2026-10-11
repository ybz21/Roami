package com.roami.app

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ServerOriginTest {
    @Test fun sameOriginAcceptsPathsAndDefaultPort() {
        assertTrue(ServerOrigin.matches("https://example.com", "https://example.com:443/projects"))
        assertTrue(ServerOrigin.matches("http://LOCALHOST:13579", "http://localhost:13579/#/settings"))
    }

    @Test fun rejectsOtherOriginsAndMalformedUrls() {
        val server = "https://example.com"
        assertFalse(ServerOrigin.matches(server, "https://example.com.evil.test/projects"))
        assertFalse(ServerOrigin.matches(server, "http://example.com/projects"))
        assertFalse(ServerOrigin.matches(server, "https://example.com:444/projects"))
        assertFalse(ServerOrigin.matches(server, "not a url"))
    }
}
