from importlib.resources import files
from pathlib import Path

SCHEMA_VERSION = 5
UPGRADES = {
    2: "0002_artifact_metadata.sql",
    3: "0003_resource_controls.sql",
    4: "0004_reminder_policy.sql",
    5: "0005_notification_delivery.sql",
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
