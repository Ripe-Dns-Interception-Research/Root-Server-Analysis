# app.py
from dash import dcc, html, Input, Output
from server import app
from visual_page import visual_layout
from compare_nsid import compare_layout

app.layout = html.Div([
    dcc.Location(id='url'),
    html.Div([
        html.A("Visualization", href="/visualization", style={"margin-right": "20px"}),
        html.A("NSID Comparison", href="/comparison")
    ], style={"margin": "20px 0"}),
    html.Div(id='page-content')
])

@app.callback(Output('page-content', 'children'), Input('url', 'pathname'))
def display_page(pathname):
    if pathname == "/comparison":
        return compare_layout
    return visual_layout

if __name__ == '__main__':
    app.run(debug=True)
