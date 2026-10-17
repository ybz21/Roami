package com.roami.app

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

class AgentNotificationTest {
    @Test fun opensOriginalConversationBranchAndMessage() {
        val event = JSONObject("""{"conversation":"conversation-id","branch":"branch-id","message":"message-id"}""")
        assertEquals("/#/home/conversation-id/branch-id/message-id", AgentNotification.path(event))
        assertEquals("agent:conversation-id", AgentNotification.key(event))
    }

    @Test fun invalidOrIncompleteTargetsFallBackToHome() {
        for (conversation in listOf("../projects", "https://evil.test", "", "has space")) {
            val event = JSONObject().put("conversation", conversation).put("branch", "branch").put("message", "message")
            assertEquals("/#/home", AgentNotification.path(event))
        }
        assertEquals("/#/home", AgentNotification.path(JSONObject("""{"conversation":"valid"}""")))
    }
}
