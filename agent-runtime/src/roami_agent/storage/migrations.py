from importlib.resources import files
from pathlib import Path

SCHEMA_VERSION = 21
UPGRADES = {
    2: "0002_artifact_metadata.sql",
    3: "0003_resource_controls.sql",
    4: "0004_reminder_policy.sql",
    5: "0005_notification_delivery.sql",
    6: "0006_artifact_retention.sql",
    7: "0007_main_conversation.sql",
    8: "0008_session_dispatches.sql",
    9: "0009_browser_tabs.sql",
    10: "0010_browser_groups.sql",
    11: "0011_task_session_closures.sql",
    12: "0012_native_sessions.sql",
    13: "0013_model_proxy.sql",
    14: "0014_upstream_model_cost.sql",
    15: "0015_swarm_collaboration.sql",
    16: "0016_swarm_memory.sql",
    17: "0017_project_okr_conversations.sql",
    18: "0018_swarm_dependency_lineage.sql",
    19: "0019_project_okr_mains.sql",
    20: "0020_swarm_members.sql",
    21: "0021_member_instances.sql",
}


def initial_schema():
    return schema_file("0001_initial.sql")


def schema_file(name):
    source = Path(__file__).resolve().parents[3] / "migrations" / name
    if source.is_file():
        return source.read_text()
    return files("roami_agent").joinpath("migrations/" + name).read_text()


def upgrade_schema(connection, version):
    for target in range(version + 1, SCHEMA_VERSION + 1):
        try:
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                + schema_file(UPGRADES[target])
                + "\n"
                + f"INSERT INTO schema_meta(version,applied_ms) VALUES({target},CAST(strftime('%s','now') AS INTEGER)*1000); COMMIT;"
            )
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
