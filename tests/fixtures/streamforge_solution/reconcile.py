"""Reference retract/upsert reconciliation; not part of the seed."""

from dataclasses import asdict

from .model import Change, Result


class Changelog:
    def __init__(self) -> None:
        self.visible: dict[tuple[str, str, int, int], Result] = {}
        self.sequence = 0

    def reconcile(self, ready: list[Result]) -> list[Change]:
        current = {result.address: result for result in ready}
        changes = []
        for address in sorted(self.visible):
            previous = self.visible[address]
            if current.get(address) != previous:
                self.sequence += 1
                changes.append(Change(self.sequence, "retract", previous))
        for address in sorted(current):
            result = current[address]
            if self.visible.get(address) != result:
                self.sequence += 1
                changes.append(Change(self.sequence, "upsert", result))
        self.visible = current
        return changes

    def forget(self, addresses: set[tuple[str, str, int, int]]) -> None:
        for address in addresses:
            self.visible.pop(address, None)

    def document(self) -> dict:
        return {
            "sequence": self.sequence,
            "visible": [asdict(self.visible[address]) for address in sorted(self.visible)],
        }

    @classmethod
    def restore(cls, document: dict) -> "Changelog":
        changelog = cls()
        sequence = document["sequence"]
        if type(sequence) is not int or sequence < 0 or not isinstance(document["visible"], list):
            raise ValueError("invalid changelog")
        for row in document["visible"]:
            result = Result(**row)
            if not all(isinstance(value, str) and value for value in (result.window, result.key)):
                raise ValueError("invalid result names")
            values = (
                result.start,
                result.end,
                result.count,
                result.total,
                result.minimum,
                result.maximum,
            )
            if any(type(value) is not int for value in values):
                raise ValueError("result fields must be integers")
            if result.start >= result.end or result.count <= 0 or result.minimum > result.maximum:
                raise ValueError("invalid result bounds")
            if not result.minimum * result.count <= result.total <= result.maximum * result.count:
                raise ValueError("invalid result aggregate")
            if result.count == 1 and not result.minimum == result.maximum == result.total:
                raise ValueError("single-event extrema disagree")
            if result.address in changelog.visible:
                raise ValueError("duplicate visible address")
            changelog.visible[result.address] = result
        if sequence < len(changelog.visible):
            raise ValueError("sequence precedes visible output")
        changelog.sequence = sequence
        return changelog
