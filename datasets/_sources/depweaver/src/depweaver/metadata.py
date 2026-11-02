"""Offline Core Metadata import/export and deterministic metadata batch reports."""

import hashlib
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import Parser

from .model import Release, normalize
from .repository import Repository
from .requirements import format, parse
from .versions import Spec, Version

REQUIRED = ("Metadata-Version", "Name", "Version")
SINGLE = (*REQUIRED, "Requires-Python", "Summary")


@dataclass(frozen=True)
class Imported:
    release: Release
    summary: str
    metadata_version: str
    source_digest: str

    def document(self) -> dict:
        return {
            "release": self.release.document(),
            "summary": self.summary,
            "metadata_version": self.metadata_version,
            "source_digest": self.source_digest,
        }


def import_metadata(text: str, *, digest: str = "", yanked: bool = False) -> Imported:
    if not isinstance(text, str) or "\x00" in text:
        raise ValueError("invalid core metadata text")
    message = Parser(policy=policy.default).parsestr(text)
    if message.defects:
        raise ValueError("malformed metadata headers")
    for field in REQUIRED:
        if not message.get(field):
            raise ValueError("missing metadata header: " + field)
    for field in SINGLE:
        if len(message.get_all(field, [])) > 1:
            raise ValueError("duplicate metadata header: " + field)
    metadata_version = str(message["Metadata-Version"])
    if metadata_version not in {"2.1", "2.2", "2.3", "2.4"}:
        raise ValueError("unsupported core metadata version")
    extras = [normalize(str(value)) for value in message.get_all("Provides-Extra", [])]
    if len(extras) != len(set(extras)):
        raise ValueError("duplicate normalized extra")
    dependencies = tuple(parse(str(value)) for value in message.get_all("Requires-Dist", []))
    release = Release(
        normalize(str(message["Name"])),
        Version.parse(str(message["Version"])),
        dependencies,
        frozenset(extras),
        Spec.parse(str(message.get("Requires-Python", "*"))),
        yanked,
        digest,
    )
    return Imported(
        release,
        str(message.get("Summary", "")),
        metadata_version,
        hashlib.sha256(text.encode()).hexdigest(),
    )


def export_metadata(release: Release, *, summary: str = "") -> str:
    if any(character in summary for character in "\r\n\x00"):
        raise ValueError("metadata summary must be a single line")
    message = EmailMessage(policy=policy.default.clone(max_line_length=0))
    message["Metadata-Version"] = "2.4"
    message["Name"] = release.name
    message["Version"] = str(release.version)
    if summary:
        message["Summary"] = summary
    if str(release.requires_python) != "*":
        message["Requires-Python"] = str(release.requires_python)
    for extra in sorted(release.extras):
        message["Provides-Extra"] = extra
    for dependency in release.dependencies:
        message["Requires-Dist"] = format(dependency)
    return message.as_string()


@dataclass(frozen=True)
class ImportFailure:
    source: str
    reason: str

    def document(self) -> dict:
        return {"source": self.source, "reason": self.reason}


@dataclass(frozen=True)
class ImportBatch:
    imported: tuple[tuple[str, Imported], ...]
    failures: tuple[ImportFailure, ...]

    @property
    def ok(self) -> bool:
        return not self.failures

    def repository(self, *, allow_partial: bool = False) -> Repository:
        if self.failures and not allow_partial:
            raise ValueError("metadata batch contains invalid sources")
        return Repository(item.release for source, item in self.imported)

    def document(self) -> dict:
        return {
            "imported": {source: item.document() for source, item in self.imported},
            "failures": [failure.document() for failure in self.failures],
        }


def import_batch(sources: dict[str, str], *, digests: dict[str, str] | None = None) -> ImportBatch:
    digests = digests or {}
    if digests.keys() - sources.keys():
        raise ValueError("digest supplied for an unknown metadata source")
    imported, failures, identities = [], [], {}
    for source, text in sorted(sources.items()):
        try:
            item = import_metadata(text, digest=digests.get(source, ""))
            if item.release.identity in identities:
                raise ValueError(
                    "duplicate release also supplied by " + identities[item.release.identity]
                )
        except (ValueError, TypeError) as error:
            failures.append(ImportFailure(source, str(error)))
        else:
            imported.append((source, item))
            identities[item.release.identity] = source
    return ImportBatch(tuple(imported), tuple(failures))


def export_batch(repository: Repository) -> dict[str, str]:
    return {
        release.name + "-" + str(release.version) + ".metadata": export_metadata(release)
        for release in repository.all()
    }
