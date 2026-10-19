
#!/usr/bin/env python3

"""
Build a match-level IPL master CSV.

Input files:
    data/processed/ipl_matches.csv
    data/processed/ipl_innings.csv
    data/processed/ipl_deliveries.csv
    data/processed/ipl_rain_flags.csv

Output:
    data/processed/ipl_master.csv

One output row per match.
Ball-level data is aggregated into innings-level summaries.
"""

import csv
import json
from collections import defaultdict
from pathlib import Path


DATA_DIR = Path("data/processed")

INPUT_FILES = {
    "matches": DATA_DIR / "ipl_matches.csv",
    "innings": DATA_DIR / "ipl_innings.csv",
    "deliveries": DATA_DIR / "ipl_deliveries.csv",
    "rain": DATA_DIR / "ipl_rain_flags.csv",
}

OUTPUT_FILE = DATA_DIR / "ipl_master.csv"


HEADERS = [
    "match_id",
    "season",
    "date",
    "event",
    "source_file",
    "team1",
    "team2",
    "team",
    "opponent",
    "innings_number",
    "innings_batting_team",
    "super_over",
    "toss_winner",
    "toss_decision",
    "winner",
    "outcome_result",
    "outcome_method",
    "result_type",
    "win_by_runs",
    "win_by_wickets",
    "no_result_flag",
    "scheduled_overs",
    "target_runs",
    "target_overs",
    "target_method",
    "revised_target_flag",
    "revised_target_overs",
    "dls_method_flag",
    "rain_indicator_flag",
    "shortened_first_innings_flag",
    "flag_reason",
    "wickets_lost_recorded",
    "legal_balls_faced",
    "innings_total_runs",
    "innings_all_out_flag",
    "innings_actual_overs",
    "data_validation_status",
]


# ---------------------------------------------------------
# General CSV helpers
# ---------------------------------------------------------

def read_csv(path):
    """Read a CSV file as a list of dictionaries."""
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def first(row, *keys, default=""):
    """Return the first non-empty value among possible column names."""
    for key in keys:
        value = row.get(key, "")
        if value is not None and str(value).strip() != "":
            return str(value).strip()

    return default


def to_int(value, default=0):
    """Safely convert a value to an integer."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def to_bool(value):
    """Interpret common CSV boolean representations."""
    return str(value).strip().lower() in {
        "1", "true", "yes", "y"
    }


def json_cell(values):
    """Store multiple innings values in a single CSV cell."""
    return json.dumps(values, ensure_ascii=False)


def get_match_id(row):
    return first(row, "match_id", "id")


def get_innings_number(row):
    return to_int(first(
        row, "innings_number", "innings", "inning", default="0"
    ))


def get_batting_team(row):
    return first(
        row,
        "innings_batting_team",
        "batting_team",
        "team",
        "bat_team",
    )


def get_super_over(row):
    return to_bool(first(row, "super_over", default="false"))


# ---------------------------------------------------------
# Match and innings indexing
# ---------------------------------------------------------

def build_master():
    matches = read_csv(INPUT_FILES["matches"])
    innings_rows = read_csv(INPUT_FILES["innings"])
    delivery_rows = read_csv(INPUT_FILES["deliveries"])
    rain_rows = read_csv(INPUT_FILES["rain"])

    # Match ID -> match metadata.
    matches_by_id = {}

    for match in matches:
        mid = get_match_id(match)

        if not mid:
            raise ValueError(
                "A match row has no match_id/id. "
                "Inspect ipl_matches.csv before continuing."
            )

        if mid in matches_by_id:
            raise ValueError(f"Duplicate match ID in matches CSV: {mid}")

        matches_by_id[mid] = match

    # Match ID -> innings metadata.
    innings_by_match = defaultdict(list)

    for innings in innings_rows:
        mid = get_match_id(innings)

        if mid:
            innings_by_match[mid].append(innings)

    # Match ID -> delivery records.
    # These are used only to validate/aggregate innings totals and balls.
    deliveries_by_match = defaultdict(list)

    for delivery in delivery_rows:
        mid = get_match_id(delivery)

        if mid:
            deliveries_by_match[mid].append(delivery)

    # Match ID -> rain flags.
    rain_by_match = {}

    for rain in rain_rows:
        mid = get_match_id(rain)

        if mid:
            rain_by_match[mid] = rain

    output_rows = []

    for mid, match in matches_by_id.items():
        inns = innings_by_match.get(mid, [])
        balls = deliveries_by_match.get(mid, [])
        rain = rain_by_match.get(mid, {})

        team1 = first(match, "team1", "team_1")
        team2 = first(match, "team2", "team_2")

        # Group deliveries by innings number, batting team, and super-over
        # status. This keeps innings summaries separate.
        balls_by_innings = defaultdict(list)

        for ball in balls:
            key = (
                get_innings_number(ball),
                get_batting_team(ball),
                get_super_over(ball),
            )
            balls_by_innings[key].append(ball)

        # Aggregate only the fields needed at match/innings level.
        innings_summaries = []

        for inn in inns:
            inn_number = get_innings_number(inn)
            batting_team = get_batting_team(inn)
            super_over = get_super_over(inn)

            key = (inn_number, batting_team, super_over)
            inn_balls = balls_by_innings.get(key, [])

            # Prefer innings-level totals when present.
            innings_total = first(
                inn,
                "innings_total_runs",
                "total_runs",
                "runs",
                default="",
            )

            if innings_total == "":
                innings_total = str(sum(
                    to_int(first(b, "total_runs", default="0"))
                    for b in inn_balls
                ))

            legal_balls = first(
                inn,
                "legal_balls_faced",
                "legal_balls",
                default="",
            )

            if legal_balls == "":
                legal_balls = str(sum(
                    1 for b in inn_balls
                    if to_bool(first(b, "is_legal_ball", default="false"))
                ))

            wickets_lost = first(
                inn,
                "wickets_lost_recorded",
                "wickets_lost",
                "wickets",
                default="",
            )

            if wickets_lost == "":
                wickets_lost = str(sum(
                    to_int(first(b, "wicket_count", default="0"))
                    for b in inn_balls
                ))

            all_out = first(
                inn,
                "innings_all_out_flag",
                "all_out_flag",
                default="",
            )

            if all_out == "":
                all_out = str(to_int(wickets_lost) >= 10).lower()

            actual_overs = first(
                inn,
                "innings_actual_overs",
                "overs",
                default="",
            )

            if actual_overs == "":
                # Cricket notation: 19.3 means 19 overs and 3 balls.
                legal = to_int(legal_balls)
                actual_overs = f"{legal // 6}.{legal % 6}"

            innings_summaries.append({
                "innings_number": inn_number,
                "team": batting_team,
                "super_over": super_over,
                "innings_total_runs": innings_total,
                "wickets_lost_recorded": wickets_lost,
                "legal_balls_faced": legal_balls,
                "innings_all_out_flag": all_out,
                "innings_actual_overs": actual_overs,
            })

        innings_summaries.sort(
            key=lambda x: (
                x["innings_number"],
                x["super_over"],
                x["team"],
            )
        )

        # Keep the innings arrays in the same order in every column.
        batting_teams = [x["team"] for x in innings_summaries]
        opponents = [
            team2 if x["team"] == team1
            else team1 if x["team"] == team2
            else ""
            for x in innings_summaries
        ]

        innings_numbers = [
            x["innings_number"] for x in innings_summaries
        ]
        super_over_flags = [
            x["super_over"] for x in innings_summaries
        ]
        innings_totals = [
            to_int(x["innings_total_runs"])
            for x in innings_summaries
        ]
        wickets_lost_values = [
            to_int(x["wickets_lost_recorded"])
            for x in innings_summaries
        ]
        legal_ball_values = [
            to_int(x["legal_balls_faced"])
            for x in innings_summaries
        ]
        all_out_flags = [
            x["innings_all_out_flag"] for x in innings_summaries
        ]
        actual_overs_values = [
            x["innings_actual_overs"] for x in innings_summaries
        ]

        # Read rain/revised-target indicators.
        revised_target_flag = first(
            rain, "revised_target_flag", default="false"
        )
        dls_method_flag = first(
            rain, "dls_method_flag", default="false"
        )
        shortened_flag = first(
            rain, "shortened_first_innings_flag", default="false"
        )

        rain_indicator = any(
            to_bool(value)
            for value in (
                revised_target_flag,
                dls_method_flag,
                shortened_flag,
            )
        )

        # Basic validation only; this does not certify official NRR.
        issues = []

        if not team1 or not team2:
            issues.append("missing_team_metadata")

        if not inns:
            issues.append("missing_innings_metadata")

        if not balls:
            issues.append("missing_delivery_records")

        if any(not x["team"] for x in innings_summaries):
            issues.append("missing_innings_batting_team")

        if len(innings_totals) != len(innings_summaries):
            issues.append("innings_total_count_mismatch")

        validation_status = (
            ";".join(issues) if issues else "basic_checks_passed"
        )

        row = {
            "match_id": mid,
            "season": first(match, "season"),
            "date": first(match, "date"),
            "event": first(match, "event", "competition"),
            "source_file": first(match, "source_file"),
            "team1": team1,
            "team2": team2,
            "team": json_cell(batting_teams),
            "opponent": json_cell(opponents),
            "innings_number": json_cell(innings_numbers),
            "innings_batting_team": json_cell(batting_teams),
            "super_over": json_cell(super_over_flags),
            "toss_winner": first(match, "toss_winner"),
            "toss_decision": first(match, "toss_decision"),
            "winner": first(match, "winner"),
            "outcome_result": first(match, "outcome_result", "result"),
            "outcome_method": first(match, "outcome_method", "method"),
            "result_type": first(match, "result_type"),
            "win_by_runs": first(match, "win_by_runs", "by_runs"),
            "win_by_wickets": first(match, "win_by_wickets", "by_wickets"),
            "no_result_flag": first(
                match, "no_result_flag", default="false"
            ),
            "scheduled_overs": first(
                match, "scheduled_overs", "overs"
            ),
            "target_runs": first(match, "target_runs"),
            "target_overs": first(match, "target_overs"),
            "target_method": first(match, "target_method"),
            "revised_target_flag": revised_target_flag,
            "revised_target_overs": first(
                rain, "revised_target_overs"
            ),
            "dls_method_flag": dls_method_flag,
            "rain_indicator_flag": str(rain_indicator).lower(),
            "shortened_first_innings_flag": shortened_flag,
            "flag_reason": first(rain, "flag_reason"),
            "wickets_lost_recorded": json_cell(wickets_lost_values),
            "legal_balls_faced": json_cell(legal_ball_values),
            "innings_total_runs": json_cell(innings_totals),
            "innings_all_out_flag": json_cell(all_out_flags),
            "innings_actual_overs": json_cell(actual_overs_values),
            "data_validation_status": validation_status,
        }

        output_rows.append(row)

    # Write exactly one output row per match in the match CSV.
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Matches in source: {len(matches)}")
    print(f"Master rows written: {len(output_rows)}")
    print(f"Columns written: {len(HEADERS)}")
    print(f"Output: {OUTPUT_FILE}")

    if len(output_rows) != len(matches):
        raise RuntimeError("Output row count does not match match count.")

    print("Row-count check passed.")
    print(
        "Important: inspect data_validation_status and verify source "
        "column names before using the table for NRR/NRRR calculations."
    )


if __name__ == "__main__":
    build_master()
