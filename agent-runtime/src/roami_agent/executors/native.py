"Native tasks execute their prepared branch through an injected Agent runner."

from roami_agent.protocol.errors import DomainError


class NativeExecutor:
    def __init__(self, run_turn):
        self.run_turn = run_turn

    async def run(self, task, run, *, turn=None):
        if turn is None or turn["branch_id"] != run["native_branch_id"]:
            raise DomainError("NATIVE_EXECUTION_CONTEXT_MISMATCH")
        text = await self.run_turn(turn, "worker", task_id=task["id"])
        return {"state": "succeeded", "summary": text}
