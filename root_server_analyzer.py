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
            {"label": "Per File (stacked)", "value": "detailed"}
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
def update_chart(selected_sources, selected_index, sort_order, selected_countries, blacklisted_countries, limit, view_mode):
    selected_month = index_to_month[int(selected_index)]

    # Step 1: Base filter by source and date (for country candidate list)
    time_source_filtered = [
        s for s in all_sites
        if s["source"] in selected_sources
        and s["Created_dt"].date() <= selected_month.replace(day=28)
        and s.get("Country")
    ]

    # Step 2: Build full list of countries (pre-limit)
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

    # Step 3: Filter fully by source, country, and date (for counting)
    fully_filtered = [
        s for s in all_sites
        if s["source"] in selected_sources
        and s.get("Country") in matching_countries
        and s["Created_dt"].date() <= selected_month.replace(day=28)
    ]

    # Step 4: Count per country
    country_counts = Counter(site["Country"] for site in fully_filtered)

    # Step 5: Build DataFrame with 0-filled values
    df = pd.DataFrame({
        "Country": all_matching_countries,
        "Sites": [country_counts.get(c, 0) for c in all_matching_countries]
    })

    # Step 6: Sort
    df.sort_values(by="Sites", ascending=(sort_order == "asc"), inplace=True)

    # Step 7: Apply limit
    if limit and isinstance(limit, int) and limit > 0:
        df = df.head(limit)

    if df.empty:
        fig = px.bar(title="No data to display with current filters")
        fig.update_layout(
            xaxis={'visible': False},
            yaxis={'visible': False},
            height=600,
            annotations=[{
                'text': "No data matches the current filters.",
                'xref': "paper",
                'yref': "paper",
                'showarrow': False,
                'font': {'size': 20}
            }]
        )
        return fig

    if view_mode == "detailed":
        # Build breakdown: Country + Source → Count
        filtered_sites = [
            s for s in all_sites
            if s["source"] in selected_sources
               and s.get("Country") in matching_countries
               and s["Created_dt"].date() <= selected_month.replace(day=28)
        ]

        # Build a (Country, Source) count matrix
        breakdown = {}
        for site in filtered_sites:
            key = (site["Country"], site["source"])
            breakdown[key] = breakdown.get(key, 0) + 1

        # Ensure every (country, source) pair appears, even if 0
        rows = []
        for country in matching_countries:
            for source in selected_sources:
                label = SOURCE_LABELS.get(source, source)
                count = breakdown.get((country, source), 0)
                rows.append({
                    "Country": country,
                    "Source": label,
                    "Count": count
                })

        df = pd.DataFrame(rows)

        # 🧠 Ensure all source labels appear — even with 0
        all_sources = sorted(
            [SOURCE_LABELS.get(src, src) for src in selected_sources]
        )

        df["Source"] = pd.Categorical(df["Source"], categories=all_sources, ordered=True)
        df.sort_values(["Country", "Source"], inplace=True)

        # Apply sorting (based on total per country)
        country_totals = df.groupby("Country")["Count"].sum().sort_values(
            ascending=(sort_order == "asc")
        )

        # Apply limit
        if limit and isinstance(limit, int) and limit > 0:
            top_countries = country_totals.head(limit).index
            df = df[df["Country"].isin(top_countries)]

        df["Country"] = pd.Categorical(df["Country"], categories=country_totals.index, ordered=True)
        df.sort_values("Country", inplace=True)

        fig = px.bar(
            df,
            x="Country",
            y="Count",
            color="Source",
            barmode="group",
            title=f"Per-letter root server breakdown on or before {selected_month.strftime('%Y-%m')}",
            category_orders={"Source": all_sources},
            height=600
        )
        fig.update_yaxes(
            showgrid=True,
            gridcolor="lightgray",  # Color of horizontal grid lines
            gridwidth=1,
            range=[0, max_site_count]
        )

        fig.update_xaxes(
            showgrid=True,
            gridcolor="lightgray",  # Color of vertical grid lines
            gridwidth=1,
            ticks="outside",
            ticklen=5,
            tickson="boundaries"
        )

        fig.update_layout(
            bargroupgap=0.3,
            plot_bgcolor="white",  # Set background of plot area to white
            paper_bgcolor="white",  # Set background of entire figure to white
                          )
        return fig

    else:
        # Step 9: Plot with fixed Y-axis
        fig = px.bar(
            df,
            x="Country",
            y="Sites",
            title=f"Root servers created on or before {selected_month.strftime('%Y-%m')}",
            labels={"Sites": "Root Servers"},
            height=600
        )
        fig.update_yaxes(
            showgrid=True,
            gridcolor="lightgray",  # Color of horizontal grid lines
            gridwidth=1,
            range=[0, max_site_count]
        )

        fig.update_layout(
            bargroupgap=0.3,
            plot_bgcolor="white",  # Set background of plot area to white
            paper_bgcolor="white",  # Set background of entire figure to white
        )
        return fig


# --- Run Server ---
if __name__ == '__main__':
    app.run(debug=False, dev_tools_ui=False)
