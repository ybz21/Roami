"""OKR Main policy for the bound native conversation provider."""

from roami_agent.protocol.serialization import encoded
from roami_agent.providers.native_conversation import NativeConversation


class NativeMain(NativeConversation):
    launch_namespace = "project-main"
    model_conflict = "PROJECT_MAIN_MODEL_CONFLICT"
    identity_mismatch = "PROJECT_MAIN_IDENTITY_MISMATCH"
    execution_failed = "PROJECT_MAIN_EXECUTION_FAILED"
    empty_result = "PROJECT_MAIN_EMPTY_RESULT"

    def prompt_intro(self):
        return (
            "You are the existing project's Main, using its bound persistent native CLI. "
            "Preserve the original Main, team, tasks, memory and recorded external action identities. "
            "Use native tools and the public roami CLI for actual work; host tool definitions are "
            "context, not native callable tools. Do not impersonate a worker or invent run IDs. "
            "Return your actual final human-readable answer; the host delivers it to the same "
            "original Main conversation. Native tool results must not be executed twice. "
            "Reconcile unknown external outcomes by their original identity before resending.\n"
            + encoded(
                {
                    "projectId": self.binding["project_id"],
                    "mainConversationId": self.binding["conversation_id"],
                    "turnId": self.turn["id"],
                }
            )
        )
