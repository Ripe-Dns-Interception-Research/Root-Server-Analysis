import dash
from dash import dcc, html, Input, Output
import plotly.express as px
import os
import json
from datetime import datetime, date
from collections import Counter
from dateutil.relativedelta import relativedelta
import pandas as pd

DATA_DIR = "data"

# Load all JSON files from the data/ folder
all_sites = []
for filename in os.listdir(DATA_DIR):
    if filename.endswith(".json"):
        filepath = os.path.join(DATA_DIR, filename)
        with open(filepath, "r") as f:
            content = json.load(f)
            for site in content.get("Sites", []):
                site["Created_dt"] = datetime.strptime(site["Created"], "%Y-%m-%dT%H:%M:%SZ")
                site["source"] = filename
                all_sites.append(site)

SOURCE_LABELS = {
    fname: fname.replace("root_", "").replace(".json", "").upper()
    for fname in set(site["source"] for site in all_sites)
}

# --- Extract filterable options ---
sources = sorted(set(site["source"] for site in all_sites))
countries = sorted(set(site["Country"] for site in all_sites if site.get("Country")))

# --- Build monthly slider steps ---
min_created = min(site["Created_dt"] for site in all_sites).date().replace(day=1)
max_created = date.today().replace(day=1)

months = []
current = max(min_created, date(2023, 1, 1))
while current <= max_created:
    months.append(current)
    current += relativedelta(months=1)

index_to_month = {i: m for i, m in enumerate(months)}

# --- Compute max number of sites per country (global peak) ---
overall_counts = Counter(site["Country"] for site in all_sites if site.get("Country"))
max_site_count = max(overall_counts.values())

# --- Dash App ---
app = dash.Dash(__name__)
app.title = "Root Server Visualization"

app.layout = html.Div([
    html.Label("View mode:"),
    dcc.RadioItems(
        id="view-mode-radio",
        options=[
            {"label": "Total per Country", "value": "total"},
            {"label": "Per Letter", "value": "detailed"}
        ],
        value="total",
        labelStyle={'display': 'inline-block', 'margin-right': '20px'}
    ),

    html.H2("Root Servers by Country"),

    html.Label("Select Root Servers:"),
    dcc.Dropdown(
        id="source-dropdown",
        options=[{"label": name, "value": name} for name in sources],
        value=sources,
        multi=True
    ),
    html.Br(),

    html.Label("Select country/countries:"),
    dcc.Dropdown(
        id="country-dropdown",
        options=[{"label": c, "value": c} for c in countries],
        value=[],  # default: no selection = all
        multi=True,
        placeholder="Select countries to display"
    ),
    html.Br(),

    html.Label("Blacklist country/countries:"),
    dcc.Dropdown(
        id="country-blacklist-dropdown",
        options=[{"label": c, "value": c} for c in countries],
        value=[],
        multi=True,
        placeholder="Exclude these countries"
    ),
    html.Br(),

    html.Label("Sort by site count:"),
    dcc.Dropdown(
        id="sort-dropdown",
        options=[
            {"label": "Descending (highest first)", "value": "desc"},
            {"label": "Ascending (lowest first)", "value": "asc"}
        ],
        value="desc",
        clearable=False,
        style={"width": "300px"}
    ),
    html.Br(),

    html.Label("Limit number of countries shown (leave empty for all):"),
    dcc.Input(
        id="limit-input",
        type="number",
        min=1,
        debounce=True
    ),
    html.Br(),

    dcc.Slider(
        id="month-slider",
        min=0,
        max=len(index_to_month) - 1,
        value=len(index_to_month) - 1,
        step=1,
        marks={i: m.strftime("%Y-%m") for i, m in index_to_month.items() if i % 2 == 0},
        updatemode="drag"
    ),

    dcc.Graph(id="bar-chart", config={"displayModeBar": False})
])

# --- Callback ---
@app.callback(
    Output("bar-chart", "figure"),
    Input("source-dropdown", "value"),
    Input("month-slider", "value"),
    Input("sort-dropdown", "value"),
    Input("country-dropdown", "value"),
    Input("country-blacklist-dropdown", "value"),
    Input("limit-input", "value"),
    Input("view-mode-radio", "value")
)
def update_chart(selected_sources, selected_index, sort_order, selected_countries, blacklisted_countries, limit,
                 view_mode):
    selected_month = index_to_month[int(selected_index)]

    if selected_countries:
        matching_countries = set(selected_countries)
    else:
        matching_countries = set(
            site["Country"] for site in all_sites
            if site["source"] in selected_sources and site.get("Country")
        )
    if blacklisted_countries:
        matching_countries -= set(blacklisted_countries)

    all_matching_countries = sorted(matching_countries)
    filtered = [
        s for s in all_sites
        if s["source"] in selected_sources and s.get("Country") in matching_countries
           and s["Created_dt"].date() <= selected_month.replace(day=28)
    ]

    if view_mode == "detailed":
        breakdown = Counter((s["Country"], s["source"]) for s in filtered)
        rows = []
        for c in matching_countries:
            for src in selected_sources:
                rows.append({
                    "Country": c,
                    "Source": SOURCE_LABELS.get(src, src),
                    "Count": breakdown.get((c, src), 0)
                })
        df = pd.DataFrame(rows)
        all_sources = sorted(SOURCE_LABELS.get(src, src) for src in selected_sources)
        df["Source"] = pd.Categorical(df["Source"], categories=all_sources, ordered=True)
        totals = df.groupby("Country")["Count"].sum().sort_values(ascending=(sort_order == "asc"))
        if limit: df = df[df["Country"].isin(totals.head(limit).index)]
        df["Country"] = pd.Categorical(df["Country"], categories=totals.index, ordered=True)
        df.sort_values(["Country", "Source"], inplace=True)

        fig = px.bar(
            df, x="Country", y="Count", color="Source", barmode="group",
            title=f"Per-letter root server breakdown on or before {selected_month.strftime('%m-%Y')}",
            category_orders={"Source": all_sources}, height=600
        )
    else:
        counts = Counter(s["Country"] for s in filtered)
        df = pd.DataFrame({
            "Country": all_matching_countries,
            "Sites": [counts.get(c, 0) for c in all_matching_countries]
        })
        df.sort_values("Sites", ascending=(sort_order == "asc"), inplace=True)
        if limit: df = df.head(limit)

        fig = px.bar(
            df, x="Country", y="Sites",
            title=f"Root servers created on or before {selected_month.strftime('%m-%Y')}",
            labels={"Sites": "Root Servers"}, height=600
        )

    fig.update_layout(
        bargroupgap=0.3,
        plot_bgcolor="white",
        paper_bgcolor="white"
    )
    fig.update_yaxes(showgrid=True, gridcolor="lightgray", gridwidth=1, range=[0, max_site_count])
    fig.update_xaxes(showgrid=True, gridcolor="lightgray", gridwidth=1, ticks="outside", ticklen=5,
                     tickson="boundaries")
    return fig


# --- Run Server ---
if __name__ == '__main__':
    app.run(debug=False, dev_tools_ui=False)
