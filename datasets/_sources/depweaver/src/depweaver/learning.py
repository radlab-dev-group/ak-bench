"""Learn conjunctions of exact decisions; clauses belong to one solve request."""

from .errors import Conflict


class Learner:
    def __init__(self) -> None:
        self.clauses: set[frozenset[tuple[str, str]]] = set()

    def reset(self) -> None:
        self.clauses.clear()

    def learn(self, conflict: Conflict) -> None:
        if conflict.culprits:
            self.clauses.add(conflict.culprits)

    def violated(
        self, assignments: frozenset[tuple[str, str]]
    ) -> frozenset[tuple[str, str]] | None:
        for clause in sorted(self.clauses, key=lambda item: (len(item), sorted(item))):
            if clause <= assignments:
                return clause
        return None

    def document(self) -> list[list[list[str]]]:
        return [
            [list(pair) for pair in sorted(clause)]
            for clause in sorted(self.clauses, key=lambda item: (len(item), sorted(item)))
        ]
