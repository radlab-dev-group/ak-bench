"""Semantic versions with numeric prerelease ordering and ignored build metadata."""

import re
from dataclasses import dataclass
from functools import total_ordering

VERSION = re.compile(
    r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?\Z"
)


@total_ordering
@dataclass(frozen=True, eq=False)
class Version:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0 for value in (self.major, self.minor, self.patch)
        ):
            raise ValueError("version components must be nonnegative integers")
        for segment in (*self.prerelease, *self.build):
            if not isinstance(segment, str) or not re.fullmatch(r"[0-9A-Za-z-]+", segment):
                raise ValueError("invalid version identifier")
        if any(
            segment.isdigit() and len(segment) > 1 and segment[0] == "0"
            for segment in self.prerelease
        ):
            raise ValueError("numeric prerelease identifier has a leading zero")

    @classmethod
    def parse(cls, text: str) -> "Version":
        if not isinstance(text, str):
            raise ValueError("version must be a string")
        match = VERSION.fullmatch(text)
        if not match:
            raise ValueError(f"invalid semantic version: {text!r}")
        major, minor, patch, prerelease, build = match.groups()
        return cls(
            int(major),
            int(minor),
            int(patch),
            tuple(prerelease.split(".")) if prerelease else (),
            tuple(build.split(".")) if build else (),
        )

    @classmethod
    def coerce(cls, text: str) -> "Version":
        if re.fullmatch(r"(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*)){0,2}", text):
            return cls.parse(text + ".0" * (2 - text.count(".")))
        return cls.parse(text)

    @property
    def core(self) -> tuple[int, int, int]:
        return self.major, self.minor, self.patch

    def __hash__(self) -> int:
        return hash((self.core, self.prerelease))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Version) and (self.core, self.prerelease) == (
            other.core,
            other.prerelease,
        )

    def __lt__(self, other: "Version") -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        if self.core != other.core:
            return self.core < other.core
        if not self.prerelease or not other.prerelease:
            return bool(self.prerelease) and not other.prerelease
        for first, second in zip(self.prerelease, other.prerelease, strict=False):
            if first == second:
                continue
            if first.isdigit() and second.isdigit():
                return int(first) < int(second)
            if first.isdigit() != second.isdigit():
                return first.isdigit()
            return first < second
        return len(self.prerelease) < len(other.prerelease)

    def __str__(self) -> str:
        text = ".".join(str(value) for value in self.core)
        if self.prerelease:
            text += "-" + ".".join(self.prerelease)
        if self.build:
            text += "+" + ".".join(self.build)
        return text

    def without_build(self) -> "Version":
        return Version(self.major, self.minor, self.patch, self.prerelease)


@dataclass(frozen=True)
class Bound:
    version: Version
    inclusive: bool


@dataclass(frozen=True)
class Interval:
    lower: Bound | None = None
    upper: Bound | None = None

    def contains(self, version: Version) -> bool:
        if self.lower and (
            version < self.lower.version
            or (version == self.lower.version and not self.lower.inclusive)
        ):
            return False
        return not (
            self.upper
            and (
                version > self.upper.version
                or (version == self.upper.version and not self.upper.inclusive)
            )
        )

    @property
    def empty(self) -> bool:
        if self.lower is None or self.upper is None:
            return False
        return self.lower.version > self.upper.version or (
            self.lower.version == self.upper.version
            and not (self.lower.inclusive and self.upper.inclusive)
        )

    def intersection(self, other: "Interval") -> "Interval":
        lower = self.lower
        if other.lower is not None and (lower is None or other.lower.version > lower.version):
            lower = other.lower
        elif other.lower is not None and lower is not None and other.lower.version == lower.version:
            lower = Bound(lower.version, lower.inclusive and other.lower.inclusive)
        upper = self.upper
        if other.upper is not None and (upper is None or other.upper.version < upper.version):
            upper = other.upper
        elif other.upper is not None and upper is not None and other.upper.version == upper.version:
            upper = Bound(upper.version, upper.inclusive and other.upper.inclusive)
        return Interval(lower, upper)


@dataclass(frozen=True)
class Comparator:
    operation: str
    version: Version

    def matches(self, candidate: Version) -> bool:
        if self.operation == "==":
            return candidate == self.version
        if self.operation == "!=":
            return candidate != self.version
        if self.operation == ">=":
            return candidate >= self.version
        if self.operation == ">":
            return candidate > self.version
        if self.operation == "<=":
            return candidate <= self.version
        if self.operation == "<":
            return candidate < self.version
        raise ValueError("unknown comparator")


@dataclass(frozen=True)
class Spec:
    alternatives: tuple[tuple[Comparator, ...], ...] = ((),)

    @classmethod
    def parse(cls, text: str = "*") -> "Spec":
        if not isinstance(text, str) or not text.strip():
            raise ValueError("empty version requirement")
        alternatives = []
        for alternative in text.split("||"):
            comparators = []
            for raw in alternative.split(","):
                raw = raw.strip()
                if not raw:
                    raise ValueError("empty version comparator")
                if raw in {"*", "x"}:
                    continue
                match = re.fullmatch(r"(>=|<=|==|!=|>|<|\^|~)?\s*(\S+)", raw)
                if not match:
                    raise ValueError("invalid version comparator")
                operation, value = match.groups()
                operation = operation or "=="
                if "*" in value or "x" in value:
                    if operation != "==":
                        raise ValueError("wildcards require equality")
                    segments = value.split(".")
                    first = next(
                        index for index, segment in enumerate(segments) if segment in {"*", "x"}
                    )
                    if any(segment not in {"*", "x"} for segment in segments[first:]) or first > 2:
                        raise ValueError("invalid wildcard version")
                    if first == 0:
                        continue
                    prefix = segments[:first]
                    lower = Version.coerce(".".join(prefix))
                    upper = (
                        Version(lower.major + 1, 0, 0)
                        if first == 1
                        else Version(lower.major, lower.minor + 1, 0)
                    )
                    comparators.extend((Comparator(">=", lower), Comparator("<", upper)))
                    continue
                version = Version.coerce(value)
                if operation == "^":
                    if version.major:
                        upper = Version(version.major + 1, 0, 0)
                    elif version.minor:
                        upper = Version(0, version.minor + 1, 0)
                    else:
                        upper = Version(0, 0, version.patch + 1)
                    comparators.extend((Comparator(">=", version), Comparator("<", upper)))
                elif operation == "~":
                    upper = (
                        Version(version.major + 1, 0, 0)
                        if value.count(".") == 0
                        else Version(version.major, version.minor + 1, 0)
                    )
                    comparators.extend((Comparator(">=", version), Comparator("<", upper)))
                else:
                    comparators.append(Comparator(operation, version))
            alternatives.append(tuple(comparators))
        return cls(tuple(alternatives))

    def matches(self, candidate: Version) -> bool:
        return any(
            all(comparator.matches(candidate) for comparator in branch)
            for branch in self.alternatives
        )

    @property
    def allows_prerelease(self) -> bool:
        return any(
            comparator.version.prerelease for branch in self.alternatives for comparator in branch
        )

    @property
    def exact(self) -> Version | None:
        if len(self.alternatives) == 1 and len(self.alternatives[0]) == 1:
            comparator = self.alternatives[0][0]
            return comparator.version if comparator.operation == "==" else None
        return None

    def __and__(self, other: "Spec") -> "Spec":
        return Spec(
            tuple(first + second for first in self.alternatives for second in other.alternatives)
        )

    def __or__(self, other: "Spec") -> "Spec":
        return Spec(self.alternatives + other.alternatives)

    def __str__(self) -> str:
        return " || ".join(
            ",".join(comparator.operation + str(comparator.version) for comparator in branch) or "*"
            for branch in self.alternatives
        )
