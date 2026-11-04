import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import t
from pathlib import Path


# ==================================================
# 1. FILE PATHS
# ==================================================

BASE_DIR = Path(__file__).resolve().parent / "data" / "processed"

INPUT_FILE = BASE_DIR / "ipl_match_metrics_new_run_1726.csv"
COEFFICIENT_FILE =   "ipl_seasons_regression_summary.csv"

OUTPUT_DIR = BASE_DIR / "hypothesis_testing_by_season"
GRAPH_DIR = OUTPUT_DIR / "graphs"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
GRAPH_DIR.mkdir(parents=True, exist_ok=True)


# ==================================================
# 2. LOAD MATCH DATA AND REGRESSION COEFFICIENTS
# ==================================================

df = pd.read_csv(INPUT_FILE)
coefficients = pd.read_csv(COEFFICIENT_FILE)

required_columns = [
    "Season",
    "NRR_Slope",
    "NRR_Intercept",
    "NRRR_Slope",
    "NRRR_Intercept"
]

missing = set(required_columns) - set(coefficients.columns)

if missing:
    raise ValueError(
        f"Missing regression columns: {missing}"
    )

coefficients["Season"] = pd.to_numeric(
    coefficients["Season"], errors="raise"
).astype(int)

if coefficients["Season"].duplicated().any():
    raise ValueError("Duplicate seasons found in regression CSV.")

df["date"] = pd.to_datetime(df["date"], errors="coerce")
df["Season"] = df["date"].dt.year

print("Match data loaded:", len(df))
print("Regression seasons loaded:", len(coefficients))


# ==================================================
# 3. CREATE TEAM-SEASON DATA
# ==================================================

team1 = pd.DataFrame({
    "Season": df["Season"],
    "MatchID": df["id"],
    "Date": df["date"],
    "Team": df["Team1"],
    "Wins": df["team1_totalwins"],
    "Matches": df["team1_totalmatches"],
    "NRR": df["netnrr1"],
    "NRRR": df["netnrrr1"]
})

team2 = pd.DataFrame({
    "Season": df["Season"],
    "MatchID": df["id"],
    "Date": df["date"],
    "Team": df["Team2"],
    "Wins": df["team2_totalwins"],
    "Matches": df["team2_totalmatches"],
    "NRR": df["netnrr2"],
    "NRRR": df["netnrrr2"]
})

team_data = pd.concat(
    [team1, team2],
    ignore_index=True
)

team_data = team_data.dropna(
    subset=[
        "Season", "Team", "Wins", "Matches",
        "NRR", "NRRR"
    ]
)

team_data = team_data[
    team_data["Matches"] > 0
].copy()

# Keep only the final cumulative record
# of each team in each IPL season.
team_data = (
    team_data
    .sort_values(["Season", "Date", "MatchID"])
    .groupby(["Season", "Team"], as_index=False)
    .tail(1)
    .copy()
)

team_data["Season"] = team_data["Season"].astype(int)


# ==================================================
# 4. CALCULATE ACTUAL AVERAGE POINTS
# ==================================================

# Actual normalized points:
# Total wins (including 0.5 wins) / Total matches
team_data["Actual"] = (
    team_data["Wins"] / team_data["Matches"]
)


# ==================================================
# 5. MERGE REGRESSION COEFFICIENTS
# ==================================================

team_data = team_data.merge(
    coefficients,
    on="Season",
    how="inner",
    validate="many_to_one"
)

if team_data.empty:
    raise ValueError(
        "No matching seasons found between the two CSV files."
    )


# ==================================================
# 6. CALCULATE PREDICTED VALUES
# ==================================================

team_data["Predicted_NRR"] = (
    team_data["NRR_Slope"] * team_data["NRR"]
    + team_data["NRR_Intercept"]
)

team_data["Predicted_NRRR"] = (
    team_data["NRRR_Slope"] * team_data["NRRR"]
    + team_data["NRRR_Intercept"]
)


# ==================================================
# 7. CALCULATE ABSOLUTE ERRORS
# ==================================================

team_data["Absolute_Error_NRR"] = (
    team_data["Actual"] - team_data["Predicted_NRR"]
).abs()

team_data["Absolute_Error_NRRR"] = (
    team_data["Actual"] - team_data["Predicted_NRRR"]
).abs()

# D = Absolute Error (NRR) - Absolute Error (NRRR)
team_data["D"] = (
    team_data["Absolute_Error_NRR"]
    - team_data["Absolute_Error_NRRR"]
)

# Save team-wise errors
team_data.to_csv(
    OUTPUT_DIR / "team_wise_absolute_errors.csv",
    index=False
)


# ==================================================
# 8. GRAPH GENERATION FUNCTION
# ==================================================

def generate_hypothesis_graph(
    season,
    t_stat,
    critical_t,
    p_value,
    dfree
):
    # Ensure the graph includes the observed t-statistic
    x_min = min(-4.5, t_stat - 0.5)
    x_max = max(4.5, t_stat + 0.5, critical_t + 0.5)

    x = np.linspace(x_min, x_max, 2000)
    y = t.pdf(x, dfree)

    fig, ax = plt.subplots(figsize=(12, 7))

    # Null hypothesis t-distribution
    ax.plot(
        x,
        y,
        color="black",
        linewidth=2.5,
        label=f"t-distribution (df = {dfree})"
    )

    # Rejection region
    ax.fill_between(
        x,
        y,
        where=(x >= critical_t),
        color="red",
        alpha=0.30,
        label="Rejection region (α = 0.05)"
    )

    # P-value region
    ax.fill_between(
        x,
        y,
        where=(x >= t_stat),
        color="royalblue",
        alpha=0.30,
        label=f"P-value area (p = {p_value:.4f})"
    )

    # Observed t-statistic
    ax.axvline(
        t_stat,
        color="blue",
        linestyle="--",
        linewidth=2,
        label=f"Observed t-statistic = {t_stat:.3f}"
    )

    # Critical t-value
    ax.axvline(
        critical_t,
        color="red",
        linestyle="-.",
        linewidth=2,
        label=f"Critical t-value = {critical_t:.3f}"
    )

    # Hypotheses
    ax.text(
        0.03,
        0.96,
        "H0: μD ≤ 0\nH1: μD > 0",
        transform=ax.transAxes,
        fontsize=12,
        verticalalignment="top",
        bbox=dict(
            boxstyle="round",
            facecolor="white",
            alpha=0.9
        )
    )

    # Statistical information
    ax.text(
        0.97,
        0.72,
        f"IPL Season: {season}\n"
        f"p-value: {p_value:.6f}\n"
        f"Significance level: 0.05",
        transform=ax.transAxes,
        fontsize=11,
        ha="right",
        bbox=dict(
            boxstyle="round",
            facecolor="white",
            alpha=0.9
        )
    )

    ax.set_title(
        f"Hypothesis Testing: NRR vs NRRR ({season})",
        fontsize=16,
        fontweight="bold"
    )

    ax.set_xlabel("t-value", fontsize=13)
    ax.set_ylabel("Probability Density", fontsize=13)
    ax.grid(alpha=0.25)
    ax.legend(loc="upper right", fontsize=9)

    plt.tight_layout()

    # Save individual season graph
    graph_path = GRAPH_DIR / f"hypothesis_test_{season}.png"
    plt.savefig(
        graph_path,
        dpi=300,
        bbox_inches="tight"
    )
    plt.close(fig)

    print("Graph saved:", graph_path)


# ==================================================
# 9. PER-SEASON PAIRED T-TEST
# ==================================================

results = []

for season, group in team_data.groupby("Season"):
    nrr_errors = group["Absolute_Error_NRR"].to_numpy()
    nrrr_errors = group["Absolute_Error_NRRR"].to_numpy()

    n = len(nrr_errors)

    if n < 2:
        print(f"Skipping season {season}: insufficient teams")
        continue

    differences = nrr_errors - nrrr_errors
    mean_nrr = np.mean(nrr_errors)
    mean_nrrr = np.mean(nrrr_errors)
    mean_difference = np.mean(differences)
    sd_difference = np.std(differences, ddof=1)
    dfree = n - 1

    if sd_difference == 0:
        print(f"Skipping season {season}: zero variance")
        continue

    t_stat = mean_difference / (sd_difference / np.sqrt(n))
    p_value = t.sf(t_stat, dfree)
    critical_t = t.ppf(0.95, dfree)

    if p_value < 0.05:
        decision = "Reject H0"
        interpretation = "Significant evidence that NRRR is more accurate"
    else:
        decision = "Fail to reject H0"
        interpretation = "Insufficient evidence that NRRR is more accurate"

    generate_hypothesis_graph(
        season,
        t_stat,
        critical_t,
        p_value,
        dfree
    )

    results.append({
        "Season": season,
        "Number_of_Paired_Observations": n,
        "MAE_NRR": mean_nrr,
        "MAE_NRRR": mean_nrrr,
        "Mean_Difference": mean_difference,
        "SD_Difference": sd_difference,
        "T_Statistic": t_stat,
        "Degrees_of_Freedom": dfree,
        "P_Value": p_value,
        "Critical_T_Value": critical_t,
        "Decision": decision,
        "Interpretation": interpretation
    })

    print("\n====================================")
    print("IPL SEASON:", season)
    print("====================================")
    print("Paired observations:", n)
    print(f"Mean MAE (NRR): {mean_nrr:.6f}")
    print(f"Mean MAE (NRRR): {mean_nrrr:.6f}")
    print(f"Mean difference: {mean_difference:.6f}")
    print(f"SD of differences: {sd_difference:.6f}")
    print(f"T-statistic: {t_stat:.6f}")
    print("Degrees of freedom:", dfree)
    print(f"P-value: {p_value:.6f}")
    print(f"Critical t-value: {critical_t:.6f}")
    print("Decision:", decision)
    print("Interpretation:", interpretation)


# ==================================================
# 10. SAVE ALL SEASON RESULTS
# ==================================================

results_df = pd.DataFrame(results)
results_df = results_df.sort_values("Season")

results_df.to_csv(
    OUTPUT_DIR / "season_wise_hypothesis_results.csv",
    index=False
)


# ==================================================
# 11. FINAL OUTPUT
# ==================================================

print("\n====================================")
print("ALL HYPOTHESIS TESTS COMPLETED")
print("====================================")
print("\nSeason-wise results:")
print(results_df.to_string(index=False))
print("\nTotal seasons tested:", len(results_df))
print("Total graphs generated:", len(results_df))
print("\nOutput directory:", OUTPUT_DIR)
print("Graphs directory:", GRAPH_DIR)
print("Results CSV:", OUTPUT_DIR / "season_wise_hypothesis_results.csv")
print("Team errors CSV:", OUTPUT_DIR / "team_wise_absolute_errors.csv")