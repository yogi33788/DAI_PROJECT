"""
Create one end-of-season correlation graph per IPL season.

Input:
    data/processed/ipl_match_metrics_new_run_1726.csv

Outputs:
    correlation_graphs/2008.correlation.png
    correlation_graphs/2009.correlation.png
    ...
    correlation_graphs/season_correlations.csv

Run this script from the project directory:
    python season_correlation.py
"""

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

# The script is expected to be in the project root.
BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "data" / "processed" / "ipl_match_metrics_new_run_1726.csv"
OUTPUT_DIR = BASE_DIR / "correlation_graphs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_end_of_season_table(season_df):
    """
    For every team, take its latest recorded row in that season.
    The input CSV stores each team's cumulative wins, matches and
    net NRR/NRRR after each match.
    """
    season_df = season_df.copy()
    season_df["date"] = pd.to_datetime(season_df["date"], errors="coerce")
    season_df = season_df.dropna(subset=["date"])
    season_df = season_df.sort_values(["date", "id"])

    team_rows = []

    for team_col, wins_col, matches_col, nrr_col, nrrr_col in [
        ("Team1", "team1_totalwins", "team1_totalmatches",
         "netnrr1", "netnrrr1"),
        ("Team2", "team2_totalwins", "team2_totalmatches",
         "netnrr2", "netnrrr2"),
    ]:
        columns = [
            team_col, wins_col, matches_col, nrr_col, nrrr_col,
            "date", "id"
        ]
        part = season_df[columns].copy()
        part = part.rename(columns={
            team_col: "team",
            wins_col: "wins",
            matches_col: "total_matches",
            nrr_col: "NRR",
            nrrr_col: "NRRR",
        })
        team_rows.append(part)

    all_team_rows = pd.concat(team_rows, ignore_index=True)
    all_team_rows = all_team_rows.dropna(subset=["team"])
    all_team_rows = all_team_rows.sort_values(["date", "id"])

    # Last appearance of each team = its latest cumulative season figures.
    end_table = (
        all_team_rows.groupby("team", as_index=False, sort=True)
        .tail(1)
        .copy()
    )

    end_table["win_percentage"] = (
        end_table["wins"] / end_table["total_matches"]
    )

    end_table = end_table.replace([float("inf"), -float("inf")], pd.NA)
    end_table = end_table.dropna(
        subset=["win_percentage", "NRR", "NRRR"]
    )
    return end_table.sort_values("team")


def make_season_graph(season, end_table):
    """Plot win/total matches against NRR and NRRR on the same axes."""
    x = end_table["win_percentage"]
    y_nrr = end_table["NRR"]
    y_nrrr = end_table["NRRR"]

    # Pearson correlation coefficients.
    corr_nrr = x.corr(y_nrr)
    corr_nrrr = x.corr(y_nrrr)

    fig, ax = plt.subplots(figsize=(10, 7))

    ax.scatter(
        x, y_nrr,
        color="royalblue",
        marker="o",
        s=75,
        label="NRR",
        alpha=0.85,
    )
    ax.scatter(
        x, y_nrrr,
        color="darkorange",
        marker="^",
        s=75,
        label="NRRR",
        alpha=0.85,
    )

    # Add team labels next to both points.
    for _, row in end_table.iterrows():
        ax.annotate(
            row["team"],
            (row["win_percentage"], row["NRR"]),
            xytext=(5, 5),
            textcoords="offset points",
            fontsize=7,
            color="royalblue",
        )
        ax.annotate(
            row["team"],
            (row["win_percentage"], row["NRRR"]),
            xytext=(5, -10),
            textcoords="offset points",
            fontsize=7,
            color="darkorange",
        )

    # Correlation values in the top-right corner of the graph.
    corr_text = (
        f"Pearson correlation\n"
        f"Win% vs NRR  = {corr_nrr:.4f}\n"
        f"Win% vs NRRR = {corr_nrrr:.4f}"
    )
    ax.text(
        0.98, 0.98, corr_text,
        transform=ax.transAxes,
        horizontalalignment="right",
        verticalalignment="top",
        fontsize=10,
        bbox=dict(boxstyle="round,pad=0.45", facecolor="white", alpha=0.8),
    )

    ax.set_title(f"{season} IPL Season: Win Percentage vs NRR and NRRR")
    ax.set_xlabel("Win / Total Matches")
    ax.set_ylabel("End-of-season NRR / NRRR")
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend()
    fig.tight_layout()

    output_file = OUTPUT_DIR / f"{season}.correlation.png"
    fig.savefig(output_file, dpi=300, bbox_inches="tight")
    plt.close(fig)

    return corr_nrr, corr_nrrr


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"CSV not found at: {INPUT_FILE}\n"
            f"Please verify that the 'data/processed' folder exists inside your project root "
            f"and contains 'ipl_match_metrics_new_run_1726.csv'."
        )

    df = pd.read_csv(INPUT_FILE)

    required_columns = {
        "date", "id", "Team1", "Team2",
        "team1_totalwins", "team1_totalmatches",
        "team2_totalwins", "team2_totalmatches",
        "netnrr1", "netnrr2", "netnrrr1", "netnrrr2",
    }
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"Missing required CSV columns: {sorted(missing)}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["season"] = df["date"].dt.year

    summary_rows = []

    for season, season_df in df.groupby("season"):
        end_table = get_end_of_season_table(season_df)

        if len(end_table) < 2:
            print(f"Skipping {season}: not enough teams to calculate correlation.")
            continue

        corr_nrr, corr_nrrr = make_season_graph(season, end_table)

        summary_rows.append({
            "season": season,
            "number_of_teams": len(end_table),
            "correlation_win_percentage_NRR": corr_nrr,
            "correlation_win_percentage_NRRR": corr_nrrr,
        })

        print(
            f"{season}: correlation with NRR = {corr_nrr:.4f}, "
            f"correlation with NRRR = {corr_nrrr:.4f}"
        )

    summary = pd.DataFrame(summary_rows)
    summary_file = OUTPUT_DIR / "season_correlations.csv"
    summary.to_csv(summary_file, index=False)

    print("\nFinished.")
    print(f"Graphs and summary CSV are saved in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
