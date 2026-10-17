from importlib.resources import files
from pathlib import Path


def initial_schema():
    source = Path(__file__).resolve().parents[3] / "migrations" / "0001_initial.sql"
    if source.is_file():
        return source.read_text()
    return files("roami_agent").joinpath("migrations/0001_initial.sql").read_text()
