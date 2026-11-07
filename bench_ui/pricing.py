"""What a run cost, estimated from a price table the operator keeps.

The history records tokens, never money: the agent CLI does not report a price
and a benchmark must not invent one. A cost is therefore an estimate made
against a table the operator supplies — prices per million tokens per model —
and it is always labelled as an estimate, never presented as a recorded number.

The table is optional. Without it the pages say "not recorded", which is the
truth; with it they say "≈ $x" and name the file the estimate came from, so a
reader can check the price behind the number.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

#: Where the price table is looked for, in order. The first that exists wins.
PRICING_FILENAMES = ("pricing.yaml", "pricing.yml")

#: A model without its own price falls back to this key, when the table has one.
DEFAULT_MODEL_KEY = "*"


@dataclass(frozen=True)
class ModelPrice:
    """The price of a model, per million tokens, in one currency."""

    input_per_million: float
    output_per_million: float
    currency: str = "USD"

    def cost_of(self, input_tokens: int | None, output_tokens: int | None) -> float:
        """What the tokens of one run would have cost at this price."""
        return (
            (input_tokens or 0) / 1_000_000 * self.input_per_million
            + (output_tokens or 0) / 1_000_000 * self.output_per_million
        )


@dataclass(frozen=True)
class PriceTable:
    """The prices the operator declared, and the file they came from.

    ``source`` is shown beside every estimate: an estimate without its origin
    is a number nobody can check.
    """

    prices: dict[str, ModelPrice]
    source: Path | None = None

    def __bool__(self) -> bool:
        return bool(self.prices)

    def price_for(self, model: str | None) -> ModelPrice | None:
        """The price of a model, or the default, or nothing at all.

        An unknown model is not priced by guessing: a benchmark that quietly
        bills an unlisted model at the default rate reports a number the table
        never said.
        """
        if model is not None and model in self.prices:
            return self.prices[model]
        return self.prices.get(DEFAULT_MODEL_KEY)

    @property
    def currency(self) -> str:
        for price in self.prices.values():
            return price.currency
        return "USD"


def load_price_table(project_root: Path | None = None) -> PriceTable:
    """Read the price table from the project root, when the operator wrote one.

    A file that cannot be read, or that is not a mapping of model to price, is
    no table at all: the pages fall back to "not recorded" rather than showing
    an estimate built from half a file.
    """
    root = Path(project_root) if project_root else Path.cwd()
    for name in PRICING_FILENAMES:
        path = root / name
        if not path.is_file():
            continue
        prices = _parse_price_table(path.read_text(encoding="utf-8"))
        if prices:
            return PriceTable(prices=prices, source=path)
    return PriceTable(prices={})


def _parse_price_table(text: str) -> dict[str, ModelPrice]:
    try:
        parsed: Any = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    body = parsed.get("models") if isinstance(parsed.get("models"), dict) else parsed
    if not isinstance(body, dict):
        return {}
    currency = str(parsed.get("currency") or "USD") if isinstance(parsed, dict) else "USD"

    prices: dict[str, ModelPrice] = {}
    for model, value in body.items():
        price = _parse_price(value, currency)
        if price is not None:
            prices[str(model)] = price
    return prices


def _parse_price(value: Any, currency: str) -> ModelPrice | None:
    """One model's price: either two numbers or a mapping that names them."""
    if isinstance(value, dict):
        try:
            return ModelPrice(
                input_per_million=float(value.get("input", 0)),
                output_per_million=float(value.get("output", 0)),
                currency=str(value.get("currency") or currency),
            )
        except (TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return ModelPrice(float(value[0]), float(value[1]), currency)
        except (TypeError, ValueError):
            return None
    return None


def estimate_run_cost(
    table: PriceTable,
    model: str | None,
    observations: dict[str, Any] | None,
) -> float | None:
    """The estimated cost of one run, or ``None`` when it cannot be estimated.

    A run whose model is not priced, or whose tokens were never recorded, is
    not zero — it is unknown, and a page that adds unknowns to a total reports
    a smaller bill than the truth.
    """
    if not table:
        return None
    price = table.price_for(model)
    if price is None or not isinstance(observations, dict):
        return None
    input_tokens = observations.get("input_tokens")
    output_tokens = observations.get("output_tokens")
    if input_tokens is None and output_tokens is None:
        return None
    return price.cost_of(
        input_tokens if isinstance(input_tokens, (int, float)) else 0,
        output_tokens if isinstance(output_tokens, (int, float)) else 0,
    )


def format_cost(amount: float | None, currency: str = "USD") -> str:
    """An estimate as text, marked as an estimate so it is not read as a bill."""
    if amount is None:
        return "not recorded"
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"≈ {symbol}{amount:,.2f}"
