from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from propintel_engine import PropIntelFilters, PropIntelOrchestrator


APP_TITLE = "PropIntel AI - Bengaluru & Mysuru Real Estate Intelligence Platform"
DATA_PATH = Path(__file__).parent / "data" / "bengaluru_mysuru_inventory.csv"


def _fmt_inr_lakh(value: float) -> str:
    return f"{value:,.1f} L"


def _score_band(score: float) -> str:
    if score >= 75:
        return "High Conviction"
    if score >= 60:
        return "Strong"
    if score >= 45:
        return "Moderate"
    return "Watchlist"


def render_sidebar(inventory: pd.DataFrame) -> PropIntelFilters:
    st.sidebar.header("Search Controls")

    all_cities = sorted(inventory["city"].unique().tolist())
    all_types = sorted(inventory["property_type"].unique().tolist())

    cities = st.sidebar.multiselect("Cities", all_cities, default=all_cities)

    min_lakh = float(inventory["price_lakh"].min())
    max_lakh = float(inventory["price_lakh"].max())
    budget = st.sidebar.slider(
        "Budget Range (Lakh INR)",
        min_value=float(round(min_lakh, 1)),
        max_value=float(round(max_lakh, 1)),
        value=(float(round(min_lakh, 1)), float(round(max_lakh, 1))),
        step=1.0,
    )

    property_types = st.sidebar.multiselect("Property Types", all_types, default=all_types)

    bhk_range = st.sidebar.slider(
        "BHK Range",
        min_value=0,
        max_value=int(inventory["bhk"].max()),
        value=(1, int(inventory["bhk"].max())),
    )

    min_yield = st.sidebar.slider(
        "Minimum Rental Yield (%)",
        min_value=0.5,
        max_value=8.0,
        value=2.0,
        step=0.1,
    )

    risk_tolerance = st.sidebar.selectbox(
        "Risk Tolerance",
        ["Conservative", "Balanced", "Aggressive"],
        index=1,
    )

    return PropIntelFilters(
        cities=cities,
        min_budget_lakh=budget[0],
        max_budget_lakh=budget[1],
        property_types=property_types,
        min_bhk=bhk_range[0],
        max_bhk=bhk_range[1],
        min_yield_pct=min_yield,
        risk_tolerance=risk_tolerance,
    )


def render_kpis(filtered: pd.DataFrame, risk_summary: dict) -> None:
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric("Matching Listings", int(filtered.shape[0]))
    with c2:
        st.metric("Median Price", _fmt_inr_lakh(float(filtered["price_lakh"].median())))
    with c3:
        st.metric("Median Yield", f"{float(filtered['rental_yield_pct'].median()):.2f}%")
    with c4:
        st.metric("High Risk Share", f"{risk_summary['high_risk_share_pct']}%")


def render_market_cards(market_summary: dict) -> None:
    st.subheader("City Pulse")

    cols = st.columns(max(len(market_summary), 1))
    for idx, (city, stats) in enumerate(market_summary.items()):
        with cols[idx]:
            st.markdown(f"### {city}")
            st.write(f"Median Price: {_fmt_inr_lakh(stats['median_price_lakh'])}")
            st.write(f"Median Price/Sqft: INR {stats['median_psf']:,.0f}")
            st.write(f"Median Yield: {stats['median_yield']}%")
            st.write(f"3Y Appreciation: {stats['avg_appreciation_3y']}%")
            st.write(f"Avg Days on Market: {stats['inventory_days']}")
            st.write(f"Listings Considered: {stats['active_listings']}")


def render_charts(filtered: pd.DataFrame) -> None:
    st.subheader("Market Visuals")

    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        fig1 = px.scatter(
            filtered,
            x="price_lakh",
            y="rental_yield_pct",
            color="city",
            size="super_builtup_sqft",
            hover_data=["locality", "property_type", "bhk"],
            title="Yield vs Price",
            labels={"price_lakh": "Price (Lakh INR)", "rental_yield_pct": "Rental Yield (%)"},
        )
        st.plotly_chart(fig1, use_container_width=True)

    with chart_col2:
        locality_top = (
            filtered.groupby(["city", "locality"], as_index=False)
            .agg(avg_appreciation=("historical_appreciation_3y_pct", "mean"))
            .sort_values("avg_appreciation", ascending=False)
            .head(10)
        )
        fig2 = px.bar(
            locality_top,
            x="avg_appreciation",
            y="locality",
            color="city",
            orientation="h",
            title="Top Localities by 3Y Appreciation",
            labels={"avg_appreciation": "3Y Appreciation (%)", "locality": "Locality"},
        )
        fig2.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig2, use_container_width=True)


def render_recommendations(recommendations: pd.DataFrame) -> None:
    st.subheader("Top Recommendations")

    top = recommendations.head(8).copy()
    top["propintel_band"] = top["propintel_score"].apply(_score_band)
    top["price_lakh"] = top["price_lakh"].round(1)
    top["price_per_sqft"] = top["price_per_sqft"].round(0)
    top["propintel_score"] = top["propintel_score"].round(1)

    show_cols = [
        "property_id",
        "city",
        "locality",
        "property_type",
        "bhk",
        "price_lakh",
        "price_per_sqft",
        "rental_yield_pct",
        "historical_appreciation_3y_pct",
        "days_on_market",
        "propintel_score",
        "propintel_band",
    ]
    st.dataframe(top[show_cols], use_container_width=True, hide_index=True)


def render_locality_table(locality_table: pd.DataFrame) -> None:
    st.subheader("Locality Intelligence Table")

    table = locality_table.copy()
    for col in ["avg_price_lakh", "avg_yield", "avg_appreciation_3y", "avg_connectivity", "avg_social_infra"]:
        table[col] = table[col].round(2)

    st.dataframe(table, use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="house", layout="wide")
    st.title(APP_TITLE)
    st.caption("Multi-agent intelligence for buy, hold, and rental decisions in Bengaluru and Mysuru")

    orchestrator = PropIntelOrchestrator(DATA_PATH)
    inventory = orchestrator.data_agent.load()

    filters = render_sidebar(inventory)

    if not filters.cities:
        st.warning("Select at least one city to run analysis.")
        return

    if not filters.property_types:
        st.warning("Select at least one property type to run analysis.")
        return

    run_clicked = st.button("Run PropIntel Analysis", type="primary", use_container_width=True)

    if not run_clicked:
        st.info("Set your filters and click Run PropIntel Analysis.")
        return

    result = orchestrator.run(filters)
    filtered = result["filtered"]

    if filtered.empty:
        st.error("No listings matched your current filters. Broaden budget, BHK, or yield settings.")
        return

    render_kpis(filtered, result["risk_summary"])
    render_market_cards(result["market_summary"])
    render_charts(filtered)

    rec_tab, loc_tab, raw_tab = st.tabs(["Recommendations", "Locality Intelligence", "Filtered Listings"])

    with rec_tab:
        render_recommendations(result["recommendations"])

    with loc_tab:
        render_locality_table(result["locality_table"])

    with raw_tab:
        show_cols = [
            "property_id",
            "city",
            "locality",
            "property_type",
            "bhk",
            "super_builtup_sqft",
            "price_lakh",
            "monthly_rent_inr",
            "rental_yield_pct",
            "historical_appreciation_3y_pct",
            "legal_risk_score",
            "flood_risk_score",
            "days_on_market",
        ]
        table = filtered[show_cols].copy()
        table["price_lakh"] = table["price_lakh"].round(1)
        st.dataframe(table.sort_values("price_lakh"), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
