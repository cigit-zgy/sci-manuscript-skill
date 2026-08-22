"""Packaged resource access."""
from importlib.resources import files

def resource(name: str):
    return files(__package__).joinpath(name)

def read_resource_text(name: str) -> str:
    return resource(name).read_text(encoding="utf-8")
