"""
charts.py — Plotly chart factory functions for Since When tracker.
No database or Streamlit imports; accepts DataFrames, returns Figures.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def _empty_fig(message: str) -> go.Figure:
    """Returns a blank figure with a centered annotation message."""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper", yref="paper",
        x=0.5, y=0.5,
        showarrow=False,
        font=dict(size=16, color="#888"),
    )
    fig.update_layout(
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        height=250,
    )
    return fig


def chart_interval_timeline(
    df: pd.DataFrame,
    item_name: str,
    expected_days: float | None = None,
) -> go.Figure:
    """
    Scatter plot of interval_days over time, with optional LOWESS trendline.
    df columns: [logged_at, interval_days]
    expected_days: draws a dashed reference line if provided.
    """
    if df.empty:
        return _empty_fig(f'Not enough data for "{item_name}" — need at least 2 logs')

    try:
        fig = px.scatter(
            df,
            x="logged_at",
            y="interval_days",
            title=f"Days Between Logs — {item_name}",
            labels={"logged_at": "Date", "interval_days": "Days Since Previous Log"},
            trendline="lowess",
            trendline_color_override="firebrick",
        )
    except Exception:
        # Fallback if statsmodels not available
        fig = px.scatter(
            df,
            x="logged_at",
            y="interval_days",
            title=f"Days Between Logs — {item_name}",
            labels={"logged_at": "Date", "interval_days": "Days Since Previous Log"},
        )

    fig.update_traces(
        selector=dict(mode="markers"),
        marker=dict(size=9, color="#1f77b4"),
    )

    if expected_days:
        fig.add_hline(
            y=expected_days,
            line_dash="dash",
            line_color="red",
            annotation_text=f"Target: {expected_days:.0f}d",
            annotation_position="top right",
        )

    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Days Since Previous Log",
        hovermode="x unified",
    )
    return fig


def chart_activity_heatmap(df: pd.DataFrame) -> go.Figure:
    """
    Activity heatmap: rows = items, columns = dates, colour = log count.
    df columns: [date, item_name, count]
    """
    if df.empty:
        return _empty_fig("No activity logged yet")

    pivot = df.pivot_table(
        index="item_name",
        columns="date",
        values="count",
        aggfunc="sum",
        fill_value=0,
    )
    # Sort columns chronologically
    pivot = pivot.sort_index(axis=1)

    fig = go.Figure(
        go.Heatmap(
            z=pivot.values.tolist(),
            x=pivot.columns.astype(str).tolist(),
            y=pivot.index.tolist(),
            colorscale="Greens",
            hoverongaps=False,
            hovertemplate="%{y}<br>%{x}<br>%{z} log(s)<extra></extra>",
        )
    )
    fig.update_layout(
        title="Activity Heatmap — All Items",
        xaxis=dict(title="Date", type="category", tickangle=-45),
        yaxis=dict(title=""),
        height=max(200, len(pivot) * 45 + 120),
        margin=dict(l=160, b=80),
    )
    return fig


def chart_frequency_comparison(df: pd.DataFrame) -> go.Figure:
    """
    Horizontal bar chart comparing average days between logs across all items.
    df columns: [item_name, avg_days, ...]
    """
    if df.empty:
        return _empty_fig("No items with 2+ logs yet")

    plot_df = df[["item_name", "avg_days"]].sort_values("avg_days")

    fig = px.bar(
        plot_df,
        x="avg_days",
        y="item_name",
        orientation="h",
        title="Average Days Between Logs — All Items",
        labels={"avg_days": "Avg Days Between Logs", "item_name": ""},
        color="avg_days",
        color_continuous_scale="RdYlGn_r",
    )
    fig.update_layout(
        coloraxis_showscale=False,
        yaxis=dict(autorange="reversed"),
        xaxis_title="Avg Days Between Logs",
    )
    fig.update_traces(
        hovertemplate="%{y}<br>Avg: %{x:.1f} days<extra></extra>",
    )
    return fig


def chart_gap_summary_table(df: pd.DataFrame) -> go.Figure:
    """
    Plotly Table summarising gap statistics per item.
    df columns: [item_name, avg_days, min_days, max_days,
                 longest_gap_days, most_recent_gap_days, log_count]
    """
    if df.empty:
        return _empty_fig("No items with 2+ logs yet")

    display = df.copy()
    for col in ["avg_days", "min_days", "max_days", "longest_gap_days", "most_recent_gap_days"]:
        display[col] = display[col].round(1)

    header_vals = [
        "Item", "Avg Days", "Min", "Max", "Longest Gap", "Recent Gap", "# Logs"
    ]
    cell_vals = [
        display["item_name"],
        display["avg_days"],
        display["min_days"],
        display["max_days"],
        display["longest_gap_days"],
        display["most_recent_gap_days"],
        display["log_count"],
    ]

    fig = go.Figure(
        go.Table(
            header=dict(
                values=header_vals,
                fill_color="#2c3e50",
                font=dict(color="white", size=12),
                align="left",
            ),
            cells=dict(
                values=cell_vals,
                fill_color=[["#f9f9f9", "#ffffff"] * (len(display) // 2 + 1)][0][: len(display)],
                align="left",
                font=dict(size=12),
            ),
        )
    )
    fig.update_layout(
        title="Gap Statistics",
        margin=dict(l=0, r=0, t=40, b=0),
        height=max(150, len(display) * 30 + 80),
    )
    return fig


def chart_interval_timeline_all(df: pd.DataFrame) -> go.Figure:
    """
    Multi-item interval scatter chart.
    df columns: [item_name, logged_at, interval_days]
    """
    if df.empty:
        return _empty_fig("No items with 2+ logs yet")

    fig = px.scatter(
        df,
        x="logged_at",
        y="interval_days",
        color="item_name",
        title="Days Between Logs — All Items",
        labels={
            "logged_at": "Date",
            "interval_days": "Days Since Previous Log",
            "item_name": "Item",
        },
    )
    fig.update_traces(marker=dict(size=9))
    fig.update_layout(hovermode="closest", legend_title_text="Item")
    return fig


def chart_ontime_vs_late(df: pd.DataFrame) -> go.Figure:
    """
    Stacked horizontal bar showing on-time vs late completions per item.
    df columns: [item_name, on_time, late, expected_days]
    """
    if df.empty:
        return _empty_fig("No items with a target and 2+ logs yet")

    df_sorted = df.sort_values("on_time", ascending=True)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="On time ✓",
        y=df_sorted["item_name"],
        x=df_sorted["on_time"],
        orientation="h",
        marker_color="#2ecc71",
        hovertemplate="%{y}<br>On time: %{x}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name="Late ✗",
        y=df_sorted["item_name"],
        x=df_sorted["late"],
        orientation="h",
        marker_color="#e74c3c",
        hovertemplate="%{y}<br>Late: %{x}<extra></extra>",
    ))
    fig.update_layout(
        barmode="stack",
        title="On Time vs Late",
        xaxis_title="Number of completions",
        yaxis_title="",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=max(250, len(df_sorted) * 45 + 120),
    )
    return fig


def chart_tasks_per_month(df: pd.DataFrame) -> go.Figure:
    """
    Bar chart of total completions per calendar month.
    df columns: [month, count]
    """
    if df.empty:
        return _empty_fig("No logs yet")

    fig = px.bar(
        df,
        x="month",
        y="count",
        title="Completions per Month",
        labels={"month": "", "count": "Completions"},
        text="count",
    )
    fig.update_traces(
        marker_color="#3498db",
        textposition="outside",
        hovertemplate="%{x}<br>%{y} completions<extra></extra>",
    )
    fig.update_layout(
        xaxis=dict(type="category", tickangle=-45),
        yaxis_title="Completions",
    )
    return fig
