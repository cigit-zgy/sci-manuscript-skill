"""Manuscript metadata serialization."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml
from ..domain.revision import parse_round, round_directory_name, round_name
from ..exceptions import WorkflowError

@dataclass(frozen=True)
class ManuscriptMetadata:
    title: str
    journal: str
    publisher: str
    language: str
    article_type: str
    round_number: int
    parent_round: int | None
    format_version: int = 1

    def to_dict(self) -> dict[str, object]:
        return {
            "workflow": {"format_version": self.format_version},
            "manuscript": {
                "title": self.title,
                "journal": self.journal,
                "publisher": self.publisher,
                "language": self.language,
                "article_type": self.article_type,
            },
            "revision": {
                "name": round_directory_name(self.round_number),
                "round": round_name(self.round_number),
                "parent": None if self.parent_round is None else round_directory_name(self.parent_round),
            },
        }

def render_metadata(metadata: ManuscriptMetadata) -> str:
    return yaml.safe_dump(metadata.to_dict(), sort_keys=False, allow_unicode=True)

def dump_metadata(metadata: ManuscriptMetadata, path: Path) -> None:
    path.write_text(render_metadata(metadata), encoding="utf-8")

def load_metadata(path: Path) -> ManuscriptMetadata:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        manuscript = data["manuscript"]
        revision = data["revision"]
        workflow = data.get("workflow", {})
        parent_raw = revision.get("parent")
        return ManuscriptMetadata(
            title=str(manuscript["title"]),
            journal=str(manuscript["journal"]),
            publisher=str(manuscript["publisher"]),
            language=str(manuscript.get("language", "en")),
            article_type=str(manuscript.get("article_type", "Research Paper")),
            round_number=parse_round(str(revision["round"])),
            parent_round=None if parent_raw is None else parse_round(str(parent_raw)),
            format_version=int(workflow.get("format_version", 1)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkflowError(f"Invalid manuscript metadata: {path}") from exc
