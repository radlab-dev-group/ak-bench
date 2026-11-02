"""Decision trail; rollback discards every assignment above a saved level."""

from dataclasses import dataclass

from .model import Release


@dataclass(frozen=True)
class Decision:
    level: int
    release: Release


class Trail:
    def __init__(self) -> None:
        self.decisions: list[Decision] = []
        self.selected: dict[str, Release] = {}

    @property
    def level(self) -> int:
        return self.decisions[-1].level if self.decisions else 0

    def assign(self, release: Release) -> None:
        if release.name in self.selected:
            raise ValueError("package already assigned")
        self.decisions.append(Decision(self.level + 1, release))
        self.selected[release.name] = release

    def rollback(self, level: int) -> None:
        if type(level) is not int or not 0 <= level <= self.level:
            raise ValueError("invalid rollback level")
        while self.decisions and self.decisions[-1].level > level:
            decision = self.decisions.pop()
            self.selected.pop(decision.release.name, None)

    def identities(self) -> frozenset[tuple[str, str]]:
        return frozenset(release.identity for release in self.selected.values())

    def document(self) -> list[dict]:
        return [
            {
                "level": decision.level,
                "package": decision.release.name,
                "version": str(decision.release.version),
            }
            for decision in self.decisions
        ]
