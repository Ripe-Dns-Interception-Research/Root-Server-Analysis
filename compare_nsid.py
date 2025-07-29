# File: compare_nsid.py

import os
import json
import base64
import io
import pandas as pd
from datetime import datetime
from dash import dcc, html, Input, Output, State, dash_table, no_update
from server import app
from dateutil.relativedelta import relativedelta


def categorize_delta(delta_days):
    months = abs(delta_days) / 30.0
    if months > 12:
        return "🔴 >1 year"
    elif months > 6:
        return "🟠 6–12 months"
    elif months > 4:
        return "🟡 4–6 months"
    elif months > 2:
        return "🟢 2–4 months"
    elif months >= 0:
        return "✅ 0–2 months"
    else:
        return "❗ Negative"


# --- Load root server data ---
data_dir = "data"
all_sites = []
for filename in os.listdir(data_dir):
    if filename.endswith(".json"):
        with open(os.path.join(data_dir, filename), "r") as f:
            content = json.load(f)
            for site in content.get("Sites", []):
                site["Created_dt"] = datetime.strptime(site["Created"], "%Y-%m-%dT%H:%M:%SZ")
                site["source"] = filename
                all_sites.append(site)

# --- Load first-seen NSID data ---
with open("data/first_seen.json", "r") as f:
    first_seen_data = {
        nsid: datetime.strptime(date_str, "%Y-%m-%d").date()
        for nsid, date_str in json.load(f).items()
    }

known_nsids = set(first_seen_data.keys())

# --- Build comparison DataFrame ---
comparison_rows = []
for site in all_sites:
    identifiers = site.get("Identifiers", [])
    for nsid in identifiers:
        if nsid in first_seen_data:
            root_created = site["Created_dt"].date()
            first_seen = first_seen_data[nsid]
            delta = (root_created - first_seen).days
            comparison_rows.append({
                "NSID": nsid,
                "Country": site.get("Country", "Unknown"),
                "Root_Created": root_created,
                "First_Seen": first_seen,
                "Delta (days)": delta,
                "Age Category": categorize_delta(delta),
                "Source": site.get("source")
            })

comparison_df = pd.DataFrame(comparison_rows)
uploaded_df = {}

# --- Page layout ---
compare_layout = html.Div([
    html.H2("NSID Comparison Tool"),
    html.P("Upload a CSV file containing NSIDs to compare against root server data."),

    dcc.Upload(
        id='upload-data',
        children=html.Div([
            '📄 Drag and Drop or ',
            html.A('Select CSV File')
        ]),
        style={
            'width': '60%', 'height': '60px', 'lineHeight': '60px',
            'borderWidth': '1px', 'borderStyle': 'dashed', 'borderRadius': '5px',
            'textAlign': 'center', 'margin': '10px'
        },
        multiple=False
    ),

    html.Div(id='column-selection-container'),
    html.Br(),

    dcc.Loading(
        dash_table.DataTable(
            id="comparison-table",
            style_table={'overflowX': 'auto'},
            style_cell={'textAlign': 'left', 'padding': '5px'},
            style_header={'fontWeight': 'bold'},
            style_data_conditional=[
                {
                    'if': {
                        'filter_query': '{Age Category} contains ">1 year"',
                        'column_id': 'Age Category'
                    },
                    'backgroundColor': '#ff9999',  # bright red
                    'color': 'black'
                },
                {
                    'if': {
                        'filter_query': '{Age Category} contains "6–12 months"',
                        'column_id': 'Age Category'
                    },
                    'backgroundColor': '#ffc266',  # orange
                    'color': 'black'
                },
                {
                    'if': {
                        'filter_query': '{Age Category} contains "4–6 months"',
                        'column_id': 'Age Category'
                    },
                    'backgroundColor': '#ffe680',  # light yellow
                    'color': 'black'
                },
                {
                    'if': {
                        'filter_query': '{Age Category} contains "2–4 months"',
                        'column_id': 'Age Category'
                    },
                    'backgroundColor': '#ccffcc',  # light green
                    'color': 'black'
                },
                {
                    'if': {
                        'filter_query': '{Age Category} contains "0–2 months"',
                        'column_id': 'Age Category'
                    },
                    'backgroundColor': '#e6ffe6',  # pale green
                    'color': 'black'
                },
                {
                    'if': {
                        'filter_query': '{Age Category} contains "Negative"',
                        'column_id': 'Age Category'
                    },
                    'backgroundColor': '#990000',
                    'color': 'white'
                },
            ]

        ),
        type="default"
    ),

    html.Div(id="missing-nsids")
])

# --- Upload file and show NSID column selector ---
@app.callback(
    Output('column-selection-container', 'children'),
    Input('upload-data', 'contents'),
    State('upload-data', 'filename')
)
def parse_uploaded_csv(contents, filename):
    if contents is None:
        return no_update

    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)

    try:
        df = pd.read_csv(io.StringIO(decoded.decode('utf-8')))
    except Exception as e:
        return html.Div(f"⚠️ Error reading file: {e}")

    uploaded_df['data'] = df

    return html.Div([
        html.Label("Select the column that contains NSIDs:"),
        dcc.Dropdown(
            id='nsid-column-dropdown',
            options=[{"label": col, "value": col} for col in df.columns],
            placeholder="Choose column...",
            style={'width': '60%'}
        )
    ])

# --- Match NSIDs and show results ---
@app.callback(
    Output("comparison-table", "data"),
    Output("comparison-table", "columns"),
    Output("missing-nsids", "children"),  # NEW
    Input("nsid-column-dropdown", "value")
)
def compare_uploaded_nsid_column(nsid_col):
    if not nsid_col or 'data' not in uploaded_df:
        return [], [], no_update

    df = uploaded_df["data"]
    nsids = set(df[nsid_col].dropna().astype(str))

    matches = comparison_df[comparison_df["NSID"].isin(nsids)].copy()
    matches.sort_values("Delta (days)", inplace=True)

    missing = sorted(nsids - set(comparison_df["NSID"]))
    if missing:
        missing_msg = html.Div([
            html.P("⚠️ NSIDs not found in first_seen.json:"),
            html.Ul([html.Li(nsid) for nsid in missing])
        ], style={"color": "red", "marginTop": "20px"})
    else:
        missing_msg = html.P("✅ All uploaded NSIDs exist in the first_seen.json database.")

    return (
        matches.to_dict("records"),
        [{"name": i, "id": i} for i in matches.columns],
        missing_msg
    )