"""Offline wheel compatibility and integrity inspection; never install archives."""

import csv
import hashlib
import io
import itertools
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .markers import Target
from .model import normalize
from .versions import Version


@dataclass(frozen=True, order=True)
class Tag:
    python: str
    abi: str
    platform: str


@dataclass(frozen=True)
class Wheel:
    filename: str
    name: str
    version: Version
    build: str
    tags: frozenset[Tag]

    @classmethod
    def parse(cls, filename: str) -> "Wheel":
        if Path(filename).name != filename or not filename.endswith(".whl"):
            raise ValueError("invalid wheel filename")
        segments = filename[:-4].split("-")
        if len(segments) not in {5, 6}:
            raise ValueError("wheel filename has wrong number of segments")
        name, version = segments[:2]
        build = segments[2] if len(segments) == 6 else ""
        if build and not re.fullmatch(r"[0-9][A-Za-z0-9_]*", build):
            raise ValueError("invalid wheel build tag")
        python, abi, platform = segments[-3:]
        if any(not re.fullmatch(r"[A-Za-z0-9_.]+", segment) for segment in (python, abi, platform)):
            raise ValueError("invalid wheel compatibility tags")
        tags = frozenset(
            Tag(*combination)
            for combination in itertools.product(
                python.split("."), abi.split("."), platform.split(".")
            )
        )
        return cls(filename, normalize(name), Version.parse(version), build, tags)


def supported_tags(target: Target) -> tuple[Tag, ...]:
    version = Version.coerce(target.python_version)
    major, minor = version.major, version.minor
    interpreter = ("cp" if target.implementation_name == "cpython" else "pp") + f"{major}{minor}"
    platforms = {
        "linux": (f"linux_{target.platform_machine}", f"manylinux_2_17_{target.platform_machine}"),
        "win32": ("win_amd64" if target.platform_machine in {"AMD64", "x86_64"} else "win32",),
        "darwin": (f"macosx_11_0_{target.platform_machine}", "macosx_11_0_universal2"),
    }.get(target.sys_platform, (target.sys_platform + "_" + target.platform_machine,))
    tags = []
    for platform in platforms:
        tags.append(Tag(interpreter, interpreter, platform))
        if target.implementation_name == "cpython" and major == 3:
            tags.extend(
                Tag(f"cp3{compatible}", "abi3", platform) for compatible in range(minor, 1, -1)
            )
        tags.append(Tag(interpreter, "none", platform))
    tags.extend((Tag(f"py{major}{minor}", "none", "any"), Tag(f"py{major}", "none", "any")))
    return tuple(dict.fromkeys(tags))


def choose(wheels: tuple[Wheel, ...], target: Target, name: str, version: Version) -> Wheel:
    ranks = {tag: index for index, tag in enumerate(supported_tags(target))}
    candidates = []
    for wheel in wheels:
        if wheel.name != normalize(name) or wheel.version != version:
            continue
        compatible = [ranks[tag] for tag in wheel.tags if tag in ranks]
        if compatible:
            candidates.append((min(compatible), wheel.filename, wheel))
    if not candidates:
        raise ValueError("no compatible wheel")
    return min(candidates, key=lambda item: item[:2])[2]


@dataclass(frozen=True)
class ArchiveReport:
    filename: str
    sha256: str
    files: tuple[str, ...]
    total_bytes: int
    metadata: str


def inspect(
    path: Path, *, expected_digest: str | None = None, max_bytes: int = 50_000_000
) -> ArchiveReport:
    import base64

    path = Path(path)
    wheel = Wheel.parse(path.name)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected_digest is not None and digest != expected_digest:
        raise ValueError("artifact checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names):
            raise ValueError("duplicate archive member")
        total = 0
        for member in archive.infolist():
            name = PurePosixPath(member.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in member.filename:
                raise ValueError("unsafe wheel archive path")
            if member.flag_bits & 1:
                raise ValueError("encrypted wheel archive is unsupported")
            total += member.file_size
            if total > max_bytes:
                raise ValueError("wheel exceeds uncompressed size limit")
        metadata_paths = [name for name in names if name.endswith(".dist-info/METADATA")]
        record_paths = [name for name in names if name.endswith(".dist-info/RECORD")]
        if len(metadata_paths) != 1 or len(record_paths) != 1:
            raise ValueError("wheel must have one METADATA and RECORD")
        metadata_root = metadata_paths[0].rsplit("/", 1)[0]
        if record_paths[0].rsplit("/", 1)[0] != metadata_root:
            raise ValueError("wheel metadata/record roots disagree")
        seen = set()
        record = archive.read(record_paths[0]).decode("utf-8")
        for row in csv.reader(io.StringIO(record)):
            if len(row) != 3:
                raise ValueError("invalid RECORD row")
            member, checksum, length = row
            if member in seen or member not in names:
                raise ValueError("duplicate or missing RECORD member")
            seen.add(member)
            if member == record_paths[0]:
                if checksum or length:
                    raise ValueError("RECORD cannot checksum itself")
                continue
            data = archive.read(member)
            expected = (
                "sha256="
                + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            )
            if checksum != expected or length != str(len(data)):
                raise ValueError("RECORD integrity mismatch")
        if seen != set(names):
            raise ValueError("RECORD does not cover every archive member")
        metadata = archive.read(metadata_paths[0]).decode("utf-8")
        return ArchiveReport(wheel.filename, digest, tuple(sorted(names)), total, metadata)
