"""Main-only sampled media and final-track transcription, without publication rights."""

from roami_agent.dispatch.publication_media import PublicationMedia
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.publication.media_runtime import media_runtime
from roami_agent.storage.publication_reviews import current_version


def register_publication_media_tools(registry, database, artifacts, factory=None):
    async def execute(args, binding):
        _, manifest = await database.call(
            lambda db: current_version(db, binding, args["versionId"])
        )
        if manifest["author"]["swarmId"] != args["swarmId"]:
            raise DomainError("PUBLICATION_PROJECT_SCOPE_CONFLICT", 403)
        if args["operation"] == "image":
            return await PublicationMedia(database, artifacts, None).image(
                binding, args["versionId"], args["artifactId"]
            )
        service = factory() if factory else media_runtime(database, artifacts)
        return await service.prepare(binding, args["versionId"], args["artifactId"])

    string = {"type": "string", "minLength": 1}
    registry.add(
        Tool(
            "swarm_publication_media",
            "Inspect a frozen original-team video/audio version using installed FFmpeg/FFprobe and the node's saved speech service. operation=inspect takes the frozen video/audio artifactId and returns sampled contact sheets, a source report and complete final-track transcription receipts; a missing dependency or uncertain request is an explicit error, never an automatic retry. Fully read returned report/transcript artifacts and call operation=image with each returned contact-sheet artifactId so actual pixels enter this Main model. Sampling is not continuous playback. This does not approve, authorize or publish anything.",
            object_schema(
                {
                    "swarmId": string,
                    "versionId": string,
                    "operation": {"type": "string", "enum": ["inspect", "image"]},
                    "artifactId": string,
                },
                ["swarmId", "versionId", "operation", "artifactId"],
            ),
            execute,
            main=True,
            effect="write",
        )
    )
