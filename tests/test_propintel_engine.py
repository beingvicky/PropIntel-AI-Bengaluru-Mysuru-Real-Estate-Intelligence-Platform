from pathlib import Path

import pandas as pd

from propintel_engine import DataAgent, PropIntelFilters, PropIntelOrchestrator


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "bengaluru_mysuru_inventory.csv"


def _all_inventory_filters(inventory: pd.DataFrame) -> PropIntelFilters:
    return PropIntelFilters(
        cities=sorted(inventory["city"].unique()),
        min_budget_lakh=float(inventory["price_lakh"].min()),
        max_budget_lakh=float(inventory["price_lakh"].max()),
        property_types=sorted(inventory["property_type"].unique()),
        min_bhk=int(inventory["bhk"].min()),
        max_bhk=int(inventory["bhk"].max()),
        min_yield_pct=0.5,
        risk_tolerance="Balanced",
    )


def test_data_agent_builds_derived_metrics() -> None:
    inventory = DataAgent(DATA_PATH).load()

    assert inventory.shape[0] == 24
    assert {"price_lakh", "price_per_sqft", "rental_yield_pct", "legal_risk_score"}.issubset(
        inventory.columns
    )

    whitefield = inventory.loc[inventory["property_id"] == "BLR-001"].iloc[0]
    assert whitefield["price_lakh"] == 98.0
    assert whitefield["price_per_sqft"] == 8305.0
    assert whitefield["rental_yield_pct"] == 4.41
    assert whitefield["legal_risk_score"] == 0


def test_default_filters_include_all_inventory_records() -> None:
    orchestrator = PropIntelOrchestrator(DATA_PATH)
    inventory = orchestrator.data_agent.load()

    result = orchestrator.run(_all_inventory_filters(inventory), inventory=inventory)

    assert result["filtered"].shape[0] == inventory.shape[0]
    assert set(result["filtered"]["property_type"]) == set(inventory["property_type"])
    assert "Plot" in set(result["filtered"]["property_type"])


def test_recommendations_are_ranked_by_score() -> None:
    orchestrator = PropIntelOrchestrator(DATA_PATH)
    inventory = orchestrator.data_agent.load()

    result = orchestrator.run(_all_inventory_filters(inventory), inventory=inventory)
    scores = result["recommendations"]["propintel_score"].tolist()

    assert scores == sorted(scores, reverse=True)
    assert result["recommendations"].iloc[0]["property_id"] == "BLR-001"


def test_empty_filter_returns_empty_tables_and_zero_risk() -> None:
    orchestrator = PropIntelOrchestrator(DATA_PATH)
    inventory = orchestrator.data_agent.load()
    filters = _all_inventory_filters(inventory)
    filters.min_budget_lakh = float(inventory["price_lakh"].max() + 1)
    filters.max_budget_lakh = float(inventory["price_lakh"].max() + 10)

    result = orchestrator.run(filters, inventory=inventory)

    assert result["filtered"].empty
    assert result["locality_table"].empty
    assert result["recommendations"].empty
    assert result["market_summary"] == {}
    assert result["risk_summary"] == {
        "high_risk_share_pct": 0.0,
        "avg_legal_risk_score": 0.0,
        "avg_flood_risk": 0.0,
    }
