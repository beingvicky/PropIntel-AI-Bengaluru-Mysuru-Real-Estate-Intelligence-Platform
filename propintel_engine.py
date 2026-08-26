import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


@dataclass
class PropIntelFilters:
    cities: List[str]
    min_budget_lakh: float
    max_budget_lakh: float
    property_types: List[str]
    min_bhk: int
    max_bhk: int
    min_yield_pct: float
    risk_tolerance: str


class DataAgent:
    """Loads, validates, and prepares property intelligence records."""

    REQUIRED_COLUMNS = {
        "property_id",
        "city",
        "locality",
        "micro_market",
        "property_type",
        "bhk",
        "super_builtup_sqft",
        "price_inr",
        "monthly_rent_inr",
        "rera_registered",
        "title_clearance",
        "legal_dispute_flag",
        "flood_risk_score",
        "connectivity_score",
        "social_infra_score",
        "days_on_market",
        "historical_appreciation_3y_pct",
    }

    def __init__(self, csv_path: Path) -> None:
        self.csv_path = csv_path

    def load(self) -> pd.DataFrame:
        df = pd.read_csv(self.csv_path)
        missing = self.REQUIRED_COLUMNS.difference(df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        df["price_lakh"] = df["price_inr"] / 100000
        df["price_per_sqft"] = (df["price_inr"] / df["super_builtup_sqft"]).round(0)
        df["rental_yield_pct"] = ((df["monthly_rent_inr"] * 12) / df["price_inr"] * 100).round(2)
        df["legal_risk_score"] = (
            (1 - df["rera_registered"].astype(int)) * 40
            + (1 - df["title_clearance"].astype(int)) * 30
            + df["legal_dispute_flag"].astype(int) * 30
        )
        return df


class LocalityScoutAgent:
    """Filters properties by user criteria and ranks localities."""

    def run(self, df: pd.DataFrame, filters: PropIntelFilters) -> Tuple[pd.DataFrame, pd.DataFrame]:
        filtered = df[
            (df["city"].isin(filters.cities))
            & (df["price_lakh"] >= filters.min_budget_lakh)
            & (df["price_lakh"] <= filters.max_budget_lakh)
            & (df["property_type"].isin(filters.property_types))
            & (df["bhk"] >= filters.min_bhk)
            & (df["bhk"] <= filters.max_bhk)
            & (df["rental_yield_pct"] >= filters.min_yield_pct)
        ].copy()

        if filtered.empty:
            return filtered, pd.DataFrame()

        localities = (
            filtered.groupby(["city", "locality", "micro_market"], as_index=False)
            .agg(
                listings=("property_id", "count"),
                avg_price_lakh=("price_lakh", "mean"),
                avg_yield=("rental_yield_pct", "mean"),
                avg_appreciation_3y=("historical_appreciation_3y_pct", "mean"),
                avg_connectivity=("connectivity_score", "mean"),
                avg_social_infra=("social_infra_score", "mean"),
            )
            .sort_values(["avg_appreciation_3y", "avg_yield"], ascending=False)
        )
        return filtered, localities


class MarketPulseAgent:
    """Builds city-level market intelligence summaries."""

    def run(self, filtered: pd.DataFrame) -> Dict[str, Dict[str, float]]:
        if filtered.empty:
            return {}

        result: Dict[str, Dict[str, float]] = {}
        for city, city_df in filtered.groupby("city"):
            result[city] = {
                "median_price_lakh": round(city_df["price_lakh"].median(), 1),
                "median_psf": round(city_df["price_per_sqft"].median(), 0),
                "median_yield": round(city_df["rental_yield_pct"].median(), 2),
                "avg_appreciation_3y": round(city_df["historical_appreciation_3y_pct"].mean(), 2),
                "inventory_days": round(city_df["days_on_market"].mean(), 1),
                "active_listings": int(city_df.shape[0]),
            }
        return result


class RiskWatchAgent:
    """Computes per-property and portfolio legal and climate risk."""

    def run(self, filtered: pd.DataFrame) -> Dict[str, float]:
        if filtered.empty:
            return {
                "high_risk_share_pct": 0.0,
                "avg_legal_risk_score": 0.0,
                "avg_flood_risk": 0.0,
            }

        high_risk = filtered[(filtered["legal_risk_score"] >= 40) | (filtered["flood_risk_score"] >= 60)]
        return {
            "high_risk_share_pct": round((len(high_risk) / len(filtered)) * 100, 1),
            "avg_legal_risk_score": round(filtered["legal_risk_score"].mean(), 1),
            "avg_flood_risk": round(filtered["flood_risk_score"].mean(), 1),
        }


class InvestmentAdvisorAgent:
    """Ranks properties based on risk-adjusted return for buyer personas."""

    RISK_WEIGHTS = {
        "Conservative": {"yield": 0.20, "appreciation": 0.25, "risk": 0.35, "liquidity": 0.20},
        "Balanced": {"yield": 0.30, "appreciation": 0.35, "risk": 0.20, "liquidity": 0.15},
        "Aggressive": {"yield": 0.35, "appreciation": 0.45, "risk": 0.05, "liquidity": 0.15},
    }

    def _normalize(self, series: pd.Series, invert: bool = False) -> pd.Series:
        floor = float(series.min())
        ceil = float(series.max())
        if math.isclose(floor, ceil):
            normalized = pd.Series([0.5] * len(series), index=series.index)
        else:
            normalized = (series - floor) / (ceil - floor)
        if invert:
            return 1 - normalized
        return normalized

    def run(self, filtered: pd.DataFrame, risk_tolerance: str) -> pd.DataFrame:
        if filtered.empty:
            return pd.DataFrame()

        scored = filtered.copy()
        weights = self.RISK_WEIGHTS.get(risk_tolerance, self.RISK_WEIGHTS["Balanced"])

        scored["n_yield"] = self._normalize(scored["rental_yield_pct"])
        scored["n_appreciation"] = self._normalize(scored["historical_appreciation_3y_pct"])
        scored["n_risk"] = self._normalize(scored["legal_risk_score"] + scored["flood_risk_score"], invert=True)
        scored["n_liquidity"] = self._normalize(scored["days_on_market"], invert=True)

        scored["propintel_score"] = (
            scored["n_yield"] * weights["yield"]
            + scored["n_appreciation"] * weights["appreciation"]
            + scored["n_risk"] * weights["risk"]
            + scored["n_liquidity"] * weights["liquidity"]
        ) * 100

        cols = [
            "property_id",
            "city",
            "locality",
            "property_type",
            "bhk",
            "super_builtup_sqft",
            "price_lakh",
            "price_per_sqft",
            "rental_yield_pct",
            "historical_appreciation_3y_pct",
            "days_on_market",
            "legal_risk_score",
            "flood_risk_score",
            "propintel_score",
        ]
        return scored[cols].sort_values("propintel_score", ascending=False).reset_index(drop=True)


class PropIntelOrchestrator:
    """Coordinates all specialized agents and returns a unified intelligence packet."""

    def __init__(self, csv_path: Path) -> None:
        self.data_agent = DataAgent(csv_path)
        self.locality_scout = LocalityScoutAgent()
        self.market_pulse = MarketPulseAgent()
        self.risk_watch = RiskWatchAgent()
        self.investment_advisor = InvestmentAdvisorAgent()

    def run(self, filters: PropIntelFilters, inventory: Optional[pd.DataFrame] = None) -> Dict[str, object]:
        inventory = inventory.copy() if inventory is not None else self.data_agent.load()
        filtered, locality_table = self.locality_scout.run(inventory, filters)
        market_summary = self.market_pulse.run(filtered)
        risk_summary = self.risk_watch.run(filtered)
        recommendations = self.investment_advisor.run(filtered, filters.risk_tolerance)

        return {
            "inventory": inventory,
            "filtered": filtered,
            "locality_table": locality_table,
            "market_summary": market_summary,
            "risk_summary": risk_summary,
            "recommendations": recommendations,
        }
