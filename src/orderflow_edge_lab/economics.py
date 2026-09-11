from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any


def _finite_number(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("economic inputs must be finite numbers")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("economic inputs must be finite numbers")
    return result


@dataclass(frozen=True)
class EconomicsPolicy:
    """Project-level fixed-cost hurdle, separate from per-trade execution costs.

    Transaction fees, spread, slippage and funding belong in trade-level validation.
    Recurring data, platform, hosting and model costs belong here so an apparently
    profitable trading process cannot ignore the infrastructure needed to operate it.
    """

    account_equity: float
    monthly_data_cost: float = 0.0
    monthly_platform_cost: float = 0.0
    monthly_compute_cost: float = 0.0
    monthly_model_cost: float = 0.0
    monthly_other_cost: float = 0.0

    def __post_init__(self) -> None:
        values = {name: _finite_number(value) for name, value in asdict(self).items()}
        if values["account_equity"] <= 0:
            raise ValueError("account_equity must be positive")
        for name, value in values.items():
            if name != "account_equity" and value < 0:
                raise ValueError("monthly project costs cannot be negative")

    @property
    def monthly_fixed_cost(self) -> float:
        return (
            self.monthly_data_cost
            + self.monthly_platform_cost
            + self.monthly_compute_cost
            + self.monthly_model_cost
            + self.monthly_other_cost
        )

    @property
    def monthly_cost_hurdle_fraction(self) -> float:
        return self.monthly_fixed_cost / self.account_equity

    @property
    def annualized_simple_cost_hurdle_fraction(self) -> float:
        return self.monthly_cost_hurdle_fraction * 12.0

    def report(self) -> dict[str, Any]:
        return {
            "account_equity": self.account_equity,
            "monthly_fixed_cost": self.monthly_fixed_cost,
            "monthly_cost_hurdle_fraction": self.monthly_cost_hurdle_fraction,
            "annualized_simple_cost_hurdle_fraction": self.annualized_simple_cost_hurdle_fraction,
            "components": {
                "data": self.monthly_data_cost,
                "platform": self.monthly_platform_cost,
                "compute": self.monthly_compute_cost,
                "model": self.monthly_model_cost,
                "other": self.monthly_other_cost,
            },
            "note": (
                "This is a fixed infrastructure hurdle only. Fees, spread, slippage, "
                "funding, taxes and capital drawdown are not included here."
            ),
        }


def load_economics_policy(mapping: dict[str, Any]) -> EconomicsPolicy:
    if not isinstance(mapping, dict):
        raise ValueError("economics policy must be an object")
    allowed = set(EconomicsPolicy.__dataclass_fields__)
    unknown = set(mapping) - allowed
    if unknown:
        raise ValueError(f"unknown economics fields: {sorted(unknown)}")
    return EconomicsPolicy(**mapping)
