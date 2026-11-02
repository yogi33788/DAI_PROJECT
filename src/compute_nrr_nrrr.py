
import pandas as pd
import numpy as np

INPUT_FILE = "ipl_match_metrics.csv"
OUTPUT_FILE = "ipl_match_metrics_new.csv"

df = pd.read_csv(INPUT_FILE)

# --------------------------------------------------
# 1. Sort chronologically within each season
# --------------------------------------------------

df["date"] = pd.to_datetime(df["date"], errors="coerce")

df = df.sort_values(
    ["season", "date", "match_id"],
    kind="stable"
).reset_index(drop=True)


# --------------------------------------------------
# 2. Helper functions
# --------------------------------------------------

def safe_float(x):
    if pd.isna(x):
        return np.nan
    try:
        return float(x)
    except (ValueError, TypeError):
        return np.nan


def safe_bool(x):
    if pd.isna(x):
        return False
    if isinstance(x, bool):
        return x
    return str(x).strip().lower() in {"true", "1", "yes"}


def get_flags(row):
    flags = []

    flag_columns = [
        "no_result_flag",
        "has_super_over_flag",
        "rain_indicator_flag",
        "shortened_first_innings_flag",
        "revised_target_flag",
        "dls_method_flag",
    ]

    for col in flag_columns:
        if col in row.index and safe_bool(row[col]):
            flags.append(col)

    if safe_bool(row.get("inn1_all_out", False)):
        flags.append("Team1_all_out")

    if safe_bool(row.get("inn2_all_out", False)):
        flags.append("Team2_all_out")

    reason = row.get("flag_reason", None)

    if pd.notna(reason) and str(reason).strip():
        flags.append(str(reason).strip())

    return "; ".join(dict.fromkeys(flags))


# --------------------------------------------------
# 3. Initialize season-specific cumulative statistics
# --------------------------------------------------

# Key = (season, team)

nrr_stats = {}

nrrr_stats = {}

# Cumulative wins and matches
wins_stats = {}


# --------------------------------------------------
# 4. Process matches chronologically
# --------------------------------------------------

records = []

for _, row in df.iterrows():

    season = row["season"]
    date = row["date"]
    match_id = row["match_id"]

    team1 = row["inn1_team_canonical"]
    team2 = row["inn2_team_canonical"]

    winner = row["winner_canonical"]

    # Actual innings statistics
    runs1 = safe_float(row["inn1_runs"])
    legalballs1 = safe_float(row["inn1_legal_balls"])

    runs2 = safe_float(row["inn2_runs"])
    legalballs2 = safe_float(row["inn2_legal_balls"])

    # NRR-adjusted runs and balls
    nrr_runs1 = safe_float(row["nrr_inn1_runs"])
    nrr_balls1 = safe_float(row["nrr_inn1_balls"])

    nrr_runs2 = safe_float(row["nrr_inn2_runs"])
    nrr_balls2 = safe_float(row["nrr_inn2_balls"])

    # Match-level NRRR
    nrrr1 = safe_float(row["rrr_inn1"])
    nrrr2 = safe_float(row["rrr_inn2"])

    # --------------------------------------------------
    # 5. Calculate match-level NRR
    # --------------------------------------------------

    if (
        pd.notna(nrr_runs1)
        and pd.notna(nrr_runs2)
        and pd.notna(nrr_balls1)
        and pd.notna(nrr_balls2)
        and nrr_balls1 > 0
        and nrr_balls2 > 0
    ):

        overs1 = nrr_balls1 / 6
        overs2 = nrr_balls2 / 6

        nrr1 = nrr_runs1 / overs1 - nrr_runs2 / overs2
        nrr2 = -nrr1

    else:
        nrr1 = np.nan
        nrr2 = np.nan

    # --------------------------------------------------
    # 6. Season-specific initialization
    # --------------------------------------------------

    key1 = (season, team1)
    key2 = (season, team2)

    for key in [key1, key2]:

        if key not in nrr_stats:
            nrr_stats[key] = {
                "runs_scored": 0.0,
                "overs_faced": 0.0,
                "runs_conceded": 0.0,
                "overs_bowled": 0.0,
            }

        if key not in nrrr_stats:
            nrrr_stats[key] = {
                "sum": 0.0,
                "count": 0,
            }

        # Initialize cumulative wins and matches
        if key not in wins_stats:
            wins_stats[key] = {
                "wins": 0,
                "matches": 0,
            }

    # --------------------------------------------------
    # 7. Update cumulative NRR for this season
    # --------------------------------------------------

    valid_nrr = (
        pd.notna(nrr_runs1)
        and pd.notna(nrr_runs2)
        and pd.notna(nrr_balls1)
        and pd.notna(nrr_balls2)
        and nrr_balls1 > 0
        and nrr_balls2 > 0
    )

    if valid_nrr:

        # Team1
        nrr_stats[key1]["runs_scored"] += nrr_runs1
        nrr_stats[key1]["overs_faced"] += nrr_balls1 / 6

        nrr_stats[key1]["runs_conceded"] += nrr_runs2
        nrr_stats[key1]["overs_bowled"] += nrr_balls2 / 6

        # Team2
        nrr_stats[key2]["runs_scored"] += nrr_runs2
        nrr_stats[key2]["overs_faced"] += nrr_balls2 / 6

        nrr_stats[key2]["runs_conceded"] += nrr_runs1
        nrr_stats[key2]["overs_bowled"] += nrr_balls1 / 6

    # --------------------------------------------------
    # 8. Update cumulative NRRR for this season
    # --------------------------------------------------

    if pd.notna(nrrr1):
        nrrr_stats[key1]["sum"] += nrrr1
        nrrr_stats[key1]["count"] += 1

    if pd.notna(nrrr2):
        nrrr_stats[key2]["sum"] += nrrr2
        nrrr_stats[key2]["count"] += 1

       # --------------------------------------------------
    # 8.5. Update cumulative wins and matches
    # --------------------------------------------------

    # Both teams have played one more match
    wins_stats[key1]["matches"] += 1
    wins_stats[key2]["matches"] += 1

    # Award wins based on the match result
    if pd.notna(winner) and winner == team1:
        wins_stats[key1]["wins"] += 1

    elif pd.notna(winner) and winner == team2:
        wins_stats[key2]["wins"] += 1

    # Draw / tie: award 0.5 win to each team
    elif pd.isna(winner) or str(winner).strip().lower() in {
        "draw", "tie", "no result", "no-result"
    }:
        wins_stats[key1]["wins"] += 0.5
        wins_stats[key2]["wins"] += 0.5

    # Cumulative values AFTER current match
    team1_totalwins = wins_stats[key1]["wins"]
    team1_totalmatches = wins_stats[key1]["matches"]

    team2_totalwins = wins_stats[key2]["wins"]
    team2_totalmatches = wins_stats[key2]["matches"]
    # --------------------------------------------------
    # 9. Calculate cumulative values AFTER current match
    # --------------------------------------------------

    def cumulative_nrr(key):

        stats = nrr_stats[key]

        if (
            stats["overs_faced"] == 0
            or stats["overs_bowled"] == 0
        ):
            return np.nan

        return (
            stats["runs_scored"] / stats["overs_faced"]
            -
            stats["runs_conceded"] / stats["overs_bowled"]
        )

    def cumulative_nrrr(key):

        stats = nrrr_stats[key]

        if stats["count"] == 0:
            return np.nan

        return stats["sum"] / stats["count"]

    netnrrr1 = cumulative_nrrr(key1)
    netnrrr2 = cumulative_nrrr(key2)

    netnrr1 = cumulative_nrr(key1)
    netnrr2 = cumulative_nrr(key2)

    # --------------------------------------------------
    # 10. Combine all flags
    # --------------------------------------------------

    all_flags = get_flags(row)

    # --------------------------------------------------
    # 11. Store output
    # --------------------------------------------------

    records.append({

        "date": date,
        "id": match_id,

        "Team1": team1,
        "Team2": team2,
        "Winner": winner,

        # Cumulative wins and matches
        "team1_totalwins": team1_totalwins,
        "team1_totalmatches": team1_totalmatches,

        "team2_totalwins": team2_totalwins,
        "team2_totalmatches": team2_totalmatches,

        "runs1": runs1,
        "legalballs1": legalballs1,

        "runs2": runs2,
        "legalballs2": legalballs2,

        "nrrr1": nrrr1,
        "nrrr2": nrrr2,

        "nrr1": nrr1,
        "nrr2": nrr2,

        "netnrrr1": netnrrr1,
        "netnrrr2": netnrrr2,

        "netnrr1": netnrr1,
        "netnrr2": netnrr2,

        "All flags": all_flags,
    })


# --------------------------------------------------
# 12. Final DataFrame in exact column order
# --------------------------------------------------

columns = [
    "date",
    "id",
    "Team1",
    "Team2",
    "Winner",

    "team1_totalwins",
    "team1_totalmatches",
    "team2_totalwins",
    "team2_totalmatches",

    "runs1",
    "legalballs1",
    "runs2",
    "legalballs2",

    "nrrr1",
    "nrrr2",

    "nrr1",
    "nrr2",

    "netnrrr1",
    "netnrrr2",

    "netnrr1",
    "netnrr2",

    "All flags",
]

output_df = pd.DataFrame(records, columns=columns)

output_df.to_csv(OUTPUT_FILE, index=False)

print("Created:", OUTPUT_FILE)
print("Total matches:", len(output_df))
print("Total seasons:", output_df["date"].dt.year.nunique())
print("Columns:", output_df.columns.tolist())
print(output_df.head())
