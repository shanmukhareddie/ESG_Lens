"""ESG Lens dashboard: the CAC 40's FY2025 emissions, each figure with the page it came from.

    streamlit run app.py
"""

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from src.portfolio.metrics import contributions, portfolio_metrics
from src.portfolio.metrics import load as load_holdings
from src.validate.evaluate import summarize

METRICS = {
    "ghg_scope1": "Scope 1",
    "ghg_scope2_location": "Scope 2, location-based",
    "ghg_scope2_market": "Scope 2, market-based",
    "ghg_scope3": "Scope 3",
    "ghg_total_location": "Total, location-based",
    "ghg_total_market": "Total, market-based",
}
STATUS = {
    "verified": "checked by hand",
    "reviewed": "reviewed by hand",
    "agreed": "both extractors agree",
    "rules_only": "rules extractor only",
    "llm_only": "LLM extractor only",
}
QUEUE = Path("data/review/review_queue.csv")


@st.cache_data
def read_data():
    emissions = pd.read_csv("data/processed/emissions.csv")
    sources = pd.read_csv("data/cac40_fy2025_sources.csv").set_index("euronext_ticker")
    companies = pd.read_csv("data/companies.csv").set_index("ticker")
    queue = pd.read_csv(QUEUE) if QUEUE.exists() else pd.DataFrame(columns=["ticker"])
    return emissions, sources, companies, queue


def page_link(url: str, page: float) -> str:
    return f"{url}#page={int(page)}" if ".pdf" in url.lower() else url


def tonnes(v: float) -> str:
    return "" if pd.isna(v) else f"{v:,.0f}"


def company_view(emissions, sources, companies, queue):
    names = sources["company_full_name"].sort_values()
    ticker = st.selectbox("Company", names.index, format_func=lambda t: f"{names[t]} ({t})")
    c, s = companies.loc[ticker], sources.loc[ticker]

    st.markdown(f"**{c['sector']}** · {c['subsector']} · {c['country']}")
    cols = st.columns(3)
    cols[0].metric("Revenue", f"€{c['revenue'] / 1000:,.1f}bn")
    cols[1].metric("Market cap", f"€{c['market_cap'] / 1000:,.1f}bn")
    cols[2].metric("Employees", "" if pd.isna(c["employees"]) else f"{c['employees']:,.0f}")
    st.markdown(f"Source: [{s['file_name']}]({s['fy2025_link']}) · report status `{s['doc_status']}`")

    e = emissions[emissions["ticker"] == ticker].copy()
    if e.empty:
        st.warning("No emissions figure has been accepted for this company yet.")
    else:
        table = (e.pivot_table(index="metric", columns="year", values="value_tco2e")
                 .reindex([m for m in METRICS if m in set(e["metric"])]))
        table.index = table.index.map(METRICS)
        st.subheader("Emissions, tCO2e")
        st.dataframe(table.map(tonnes).sort_index(axis=1, ascending=False), width="stretch")

        checked = e["identity_ok"].dropna()
        if len(checked) and checked.astype(bool).all():
            st.success("The totals equal Scope 1 + Scope 2 + Scope 3.")
        elif len(checked):
            st.error("The totals do not equal Scope 1 + Scope 2 + Scope 3.")

        st.subheader("Evidence")
        e["metric"] = e["metric"].map(METRICS)
        e["status"] = e["status"].map(STATUS).fillna(e["status"])
        e["page_link"] = [page_link(s["fy2025_link"], p) for p in e["page"]]
        e["value_tco2e"] = e["value_tco2e"].map(tonnes)
        st.dataframe(
            e.sort_values(["year", "metric"], ascending=[False, True])[
                ["metric", "year", "value_tco2e", "status", "page_link", "quote"]],
            hide_index=True, width="stretch",
            column_config={
                "value_tco2e": "tCO2e",
                "page_link": st.column_config.LinkColumn("page", display_text=r"#page=(\d+)$"),
                "quote": st.column_config.TextColumn("row as printed", width="large"),
            },
        )

    waiting = (queue["ticker"] == ticker).sum()
    if waiting:
        st.info(f"{waiting} more values for this company are waiting for review: "
                "the two extractors disagree or the totals do not add up.")


def portfolio_view():
    st.markdown("€100m in the CAC 40, weighted by market cap. Definitions in `docs/portfolio_metrics.md`.")
    h = load_holdings()
    m = portfolio_metrics(h)
    for col in ("value", "low", "high"):
        m[col] = m[col].map(lambda v: f"{v:,.1f}")
    st.dataframe(m, hide_index=True, width="stretch")

    st.subheader("Who the financed emissions come from")
    top = contributions(h).head(10).reset_index()
    chart = alt.Chart(top).mark_bar().encode(
        x=alt.X("financed_tco2e:Q", title="financed tCO2e, scopes 1+2+3"),
        y=alt.Y("ticker:N", sort="-x", title=None),
        tooltip=[alt.Tooltip("ticker:N"), alt.Tooltip("weight:Q", format=".1%", title="portfolio weight"),
                 alt.Tooltip("share_of_financed:Q", format=".1%", title="share of financed emissions")],
    )
    st.altair_chart(chart, width="stretch")
    lead = top.iloc[0]
    st.caption(f"The largest contributor, {lead['ticker']}, is {lead['weight']:.1%} of the portfolio "
               f"but {lead['share_of_financed']:.0%} of its financed emissions. Scope 3 drives most of it.")


def quality_view():
    st.markdown("Each extractor scored against values labelled by hand. "
                "Details in `docs/extraction_report.md`.")
    for title, path in [("Development set: 12 companies, used while building the extractors",
                         "data/processed/evaluation.csv"),
                        ("Test set: 4 companies, not looked at while building",
                         "data/processed/test/evaluation.csv")]:
        st.subheader(title)
        scores = summarize(pd.read_csv(path), ["extractor"])
        scores[["precision", "recall"]] = scores[["precision", "recall"]].map(lambda v: f"{v:.1%}")
        st.dataframe(scores, hide_index=True, width="stretch")


st.set_page_config(page_title="ESG Lens", layout="wide")
st.title("ESG Lens")
st.caption("FY2025 greenhouse gas emissions of the CAC 40, read from the companies' own reports. "
           "Every figure links to the page it was read from.")

emissions, sources, companies, queue = read_data()
company_tab, portfolio_tab, quality_tab = st.tabs(["Company", "Portfolio", "Extraction quality"])
with company_tab:
    company_view(emissions, sources, companies, queue)
with portfolio_tab:
    portfolio_view()
with quality_tab:
    quality_view()
