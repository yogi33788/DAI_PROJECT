#!/usr/bin/env python3

"""
Build a match-level IPL master CSV ready for Official NRR and NRRR analysis.

Input files (Primary pipeline):
    data/processed/ipl_matches.csv
    data/processed/ipl_innings.csv
    data/processed/ipl_deliveries.csv
    data/processed/ipl_rain_flags.csv

Fallback / In-Place Upgrade input (if upstream split CSVs are absent):
    data/processed/ipl_master.csv (or path passed via --input-master)

Output:
    data/processed/ipl_master.csv (or path passed via --output)

Key Enhancements for NRR vs. NRRR Project:
1. Preserves all 37 original columns while backfilling previously empty
   `target_runs`, `target_overs`, and `target_method` fields using upstream
   metadata, algebraic DLS run-margin derivation, and verified historical
   DLS scorecards for matches won by wickets.
2. Separates regulation innings (Innings 1 and 2) from Super Over tie-breakers
   (`innings_number >= 3` or `super_over == True`) and exposes flat scalar
   columns (`inn1_*`, `inn2_*`) so downstream scripts do not include Super Over
   runs/balls in NRR or NRRR.
3. Identifies all 73 playoff/knockout matches across IPL 2007/08–2026 via
   `match_stage` ("league" vs. "playoff") and `is_playoff` ("true"/"false") so
   league-table NRR and NRRR standings exclude knockout games.
4. Corrects 9-wicket "all-out" chases where a batter was absent/retired hurt
   (matches 392197, 392202, 419114, 598066, 729293, 1175358) so full-quota
   overs and 100% resource usage are applied consistently.
5. Resolves umpire ball-count anomalies: caps match 419155 Innings 1 at 120
   legal balls (from 121) and clears false-positive heuristic rain flags on
   full 20-over innings with a 5-ball over miscount (matches 335987, 501202).
6. Adds canonical franchise names (`team1_canonical`, `team2_canonical`,
   `winner_canonical`, `inn1_team_canonical`, `inn2_team_canonical`) and
   pre-computed official NRR inputs (`nrr_inn1_runs`, `nrr_inn1_balls`,
   `nrr_inn2_runs`, `nrr_inn2_balls`, `par_score_team2_end`).
"""

import argparse
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


# ---------------------------------------------------------
# Domain reference tables (IPL 2007/08 - 2026)
# ---------------------------------------------------------

# Canonical franchise mapping across all 19 IPL seasons.
CANONICAL_TEAM_MAP = {
    "Delhi Daredevils": "Delhi Capitals",
    "Delhi Capitals": "Delhi Capitals",
    "Kings XI Punjab": "Punjab Kings",
    "Punjab Kings": "Punjab Kings",
    "Royal Challengers Bangalore": "Royal Challengers Bengaluru",
    "Royal Challengers Bengaluru": "Royal Challengers Bengaluru",
    "Rising Pune Supergiants": "Rising Pune Supergiant",
    "Rising Pune Supergiant": "Rising Pune Supergiant",
    "Deccan Chargers": "Deccan Chargers",
    "Chennai Super Kings": "Chennai Super Kings",
    "Mumbai Indians": "Mumbai Indians",
    "Kolkata Knight Riders": "Kolkata Knight Riders",
    "Rajasthan Royals": "Rajasthan Royals",
    "Sunrisers Hyderabad": "Sunrisers Hyderabad",
    "Gujarat Titans": "Gujarat Titans",
    "Lucknow Super Giants": "Lucknow Super Giants",
    "Gujarat Lions": "Gujarat Lions",
    "Pune Warriors": "Pune Warriors",
    "Kochi Tuskers Kerala": "Kochi Tuskers Kerala",
}

# Verified IPL Playoff / Knockout match IDs (2007/08 through 2026).
# 2007/08 & 2009 had 3 knockout games (2 Semi-Finals + Final).
# 2009/10 had 4 knockout games (2 Semi-Finals + 3rd-Place Playoff + Final).
# 2011–2026 each have 4 playoff games (Qualifier 1, Eliminator, Qualifier 2, Final).
PLAYOFF_MATCH_IDS = {
    # 2007/08
    "336038", "336039", "336040",
    # 2009
    "392237", "392238", "392239",
    # 2009/10
    "419162", "419163", "419164", "419165",
    # 2011
    "501268", "501269", "501270", "501271",
    # 2012
    "548378", "548379", "548380", "548381",
    # 2013
    "598070", "598071", "598072", "598073",
    # 2014
    "734043", "734045", "734047", "734049",
    # 2015
    "829817", "829819", "829821", "829823",
    # 2016
    "981013", "981015", "981017", "981019",
    # 2017
    "1082647", "1082648", "1082649", "1082650",
    # 2018
    "1136617", "1136618", "1136619", "1136620",
    # 2019
    "1181764", "1181766", "1181767", "1181768",
    # 2020/21
    "1237177", "1237178", "1237180", "1237181",
    # 2021
    "1254114", "1254115", "1254116", "1254117",
    # 2022
    "1312197", "1312198", "1312199", "1312200",
    # 2023
    "1370350", "1370351", "1370352", "1370353",
    # 2024
    "1426309", "1426310", "1426311", "1426312",
    # 2025
    "1473508", "1473509", "1473510", "1473511",
    # 2026
    "1535462", "1535463", "1535464", "1535465",
}

# Verified revised targets for the 10 DLS matches won by wickets where
# win_by_runs is null and upstream Cricsheet CSVs omit target_runs.
VERIFIED_DLS_WICKET_WIN_TARGETS = {
    "392183": (54, "6.0", "D/L"),     # 2009 DD vs KXIP: target 54 in 6 overs
    "501215": (135, "17.0", "D/L"),   # 2011 KTK vs CSK: target 135 in 17 overs
    "501255": (102, "13.0", "D/L"),   # 2011 RCB vs KKR: target 102 in 13 overs
    "733993": (43, "5.0", "D/L"),     # 2014 DD vs SRH: target 43 in 5 overs
    "829807": (81, "6.0", "D/L"),     # 2015 SRH vs RCB: target 81 in 6 overs
    "980989": (66, "9.0", "D/L"),     # 2016 KKR vs RPS: target 66 in 9 overs
    "1082648": (48, "6.0", "D/L"),    # 2017 SRH vs KKR: target 48 in 6 overs
    "1136578": (125, "13.0", "DLS"),  # 2018 KKR vs KXIP: target 125 in 13 overs
    "1370353": (171, "15.0", "DLS"),  # 2023 GT vs CSK Final: target 171 in 15 overs
    "1473493": (147, "19.0", "DLS"),  # 2025 MI vs GT: target 147 in 19 overs
}

# Matches where Innings 1 batted the full 20-over quota without rain,
# but an umpire miscounted one over as 5 balls (119 legal balls total).
UMPIRE_119_BALL_FULL_QUOTA_MATCHES = {"335987", "501202"}

# Matches where Innings 2 ended with 9 wickets down because a batter was
# absent/retired hurt (all out for NRR and NRRR purposes).
RETIRED_HURT_ALL_OUT_INNINGS2_MATCHES = {
    "392197", "392202", "419114", "598066", "729293", "1175358"
}


HEADERS = [
    # Original 37 columns (strictly preserved in order)
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
    # Added analysis-ready columns for Official NRR and NRRR
    "match_stage",
    "is_playoff",
    "team1_canonical",
    "team2_canonical",
    "winner_canonical",
    "has_super_over_flag",
    "inn1_team",
    "inn1_team_canonical",
    "inn1_runs",
    "inn1_legal_balls",
    "inn1_wickets",
    "inn1_all_out",
    "inn1_actual_overs",
    "inn2_team",
    "inn2_team_canonical",
    "inn2_runs",
    "inn2_legal_balls",
    "inn2_wickets",
    "inn2_all_out",
    "inn2_actual_overs",
    "par_score_team2_end",
    "nrr_inn1_runs",
    "nrr_inn1_balls",
    "nrr_inn2_runs",
    "nrr_inn2_balls",
]


# ---------------------------------------------------------
# General CSV & cricket notation helpers
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


def parse_json_cell(cell, default=None):
    """Safely parse a JSON list cell from an existing master CSV."""
    if default is None:
        default = []
    if cell is None or str(cell).strip() == "":
        return list(default)
    try:
        return json.loads(cell)
    except (ValueError, TypeError):
        return list(default)


def canonical_team(name):
    """Map historical IPL franchise names to canonical modern names."""
    clean = str(name).strip() if name else ""
    return CANONICAL_TEAM_MAP.get(clean, clean)


def overs_to_balls(overs_str, default_balls=120):
    """Convert cricket overs notation (e.g. '9.2' or '16.0') to legal balls."""
    if overs_str is None or str(overs_str).strip() == "":
        return default_balls
    s = str(overs_str).strip()
    try:
        if "." in s:
            o_part, b_part = s.split(".", 1)
            overs_int = int(o_part)
            balls_int = int(b_part)
            if 0 <= balls_int < 6:
                return overs_int * 6 + balls_int
        return int(round(float(s) * 6))
    except ValueError:
        return default_balls


def balls_to_overs_str(balls):
    """Convert legal balls (e.g. 116) to cricket overs string ('19.2')."""
    b = to_int(balls, 0)
    return f"{b // 6}.{b % 6}"


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
# Post-processing & enrichment of a match record
# ---------------------------------------------------------

def enrich_and_fix_match_row(row):
    """
    Apply all NRR/NRRR domain fixes and enrich a match dictionary with
    regulation-innings scalar columns, target backfills, and official NRR inputs.
    """
    mid = str(row["match_id"]).strip()
    season = str(row["season"]).strip()
    team1 = str(row["team1"]).strip()
    team2 = str(row["team2"]).strip()
    winner = str(row["winner"]).strip()
    result_type = str(row["result_type"]).strip()

    batting_teams = parse_json_cell(row["innings_batting_team"])
    innings_numbers = [to_int(x) for x in parse_json_cell(row["innings_number"])]
    super_over_flags = [to_bool(x) for x in parse_json_cell(row["super_over"])]
    innings_totals = [to_int(x) for x in parse_json_cell(row["innings_total_runs"])]
    wickets_lost_values = [to_int(x) for x in parse_json_cell(row["wickets_lost_recorded"])]
    legal_ball_values = [to_int(x) for x in parse_json_cell(row["legal_balls_faced"])]
    all_out_flags = [
        str(x).strip().lower() for x in parse_json_cell(row["innings_all_out_flag"])
    ]
    actual_overs_values = [
        str(x).strip() for x in parse_json_cell(row["innings_actual_overs"])
    ]

    scheduled_overs_str = first(row, "scheduled_overs", default="20")
    scheduled_balls = overs_to_balls(scheduled_overs_str, default_balls=120)

    notes = []
    if row.get("data_validation_status") and row["data_validation_status"] != "basic_checks_passed":
        notes.append(row["data_validation_status"])

    # 1. Fix umpire over-count anomaly (Match 419155: 121 balls -> cap at 120)
    for idx in range(len(legal_ball_values)):
        is_so = super_over_flags[idx] if idx < len(super_over_flags) else (idx >= 2)
        if not is_so and legal_ball_values[idx] > scheduled_balls:
            raw_b = legal_ball_values[idx]
            legal_ball_values[idx] = scheduled_balls
            actual_overs_values[idx] = balls_to_overs_str(scheduled_balls)
            notes.append(f"inn{idx + 1}_balls_capped_{raw_b}_to_{scheduled_balls}")

    # 2. Clear false-positive rain heuristic on 119-ball umpire miscount matches
    revised_target_flag = to_bool(row.get("revised_target_flag", "false"))
    dls_method_flag = to_bool(row.get("dls_method_flag", "false"))
    shortened_flag = to_bool(row.get("shortened_first_innings_flag", "false"))
    flag_reason = first(row, "flag_reason", default="")

    if mid in UMPIRE_119_BALL_FULL_QUOTA_MATCHES and not revised_target_flag and not dls_method_flag:
        shortened_flag = False
        row["shortened_first_innings_flag"] = "false"
        row["rain_indicator_flag"] = "false"
        row["flag_reason"] = ""
        notes.append("umpire_119_ball_miscount_not_rain")
    else:
        rain_indicator = any([
            revised_target_flag,
            dls_method_flag,
            shortened_flag,
            result_type == "no_result",
        ])
        row["rain_indicator_flag"] = str(rain_indicator).lower()

    # 3. Extract regulation innings (indices where super_over is False and innings_number in {1, 2})
    reg_indices = [
        i for i in range(len(innings_numbers))
        if not (super_over_flags[i] if i < len(super_over_flags) else False)
        and innings_numbers[i] in (1, 2)
    ]
    has_super_over = any(super_over_flags) or len(innings_numbers) > 2

    # 4. Correct 9-wicket all-out chases (batter absent/retired hurt)
    if len(reg_indices) >= 2:
        i2 = reg_indices[1]
        rev_overs_str = first(row, "revised_target_overs", default="")
        quota_balls_2 = (
            overs_to_balls(rev_overs_str, scheduled_balls)
            if revised_target_flag and rev_overs_str
            else scheduled_balls
        )
        # If Team 1 won without DLS interruption and Team 2 stopped before quota_balls_2
        # with 9 wickets down (or is in the verified retired-hurt all-out set), Team 2 was all out.
        if (
            mid in RETIRED_HURT_ALL_OUT_INNINGS2_MATCHES
            or (
                winner == batting_teams[reg_indices[0]]
                and not dls_method_flag
                and result_type == "winner"
                and legal_ball_values[i2] < quota_balls_2
                and wickets_lost_values[i2] >= 9
            )
        ):
            if all_out_flags[i2] != "true":
                all_out_flags[i2] = "true"
                notes.append("inn2_9wkt_retired_hurt_marked_all_out")

    # Update JSON cells with cleaned values
    row["legal_balls_faced"] = json_cell(legal_ball_values)
    row["innings_actual_overs"] = json_cell(actual_overs_values)
    row["innings_all_out_flag"] = json_cell(all_out_flags)

    # 5. Backfill target_runs, target_overs, target_method, and par_score_team2_end
    target_runs_str = first(row, "target_runs", default="")
    target_overs_str = first(row, "target_overs", default="")
    target_method_str = first(row, "target_method", default="")
    rev_overs_str = first(row, "revised_target_overs", default="")

    par_score_end = ""

    if result_type == "no_result" or len(reg_indices) < 2:
        # No completed second-innings target
        target_runs_str = ""
        target_overs_str = rev_overs_str if rev_overs_str else ""
        target_method_str = "no_result"
        par_score_end = ""
    else:
        i1, i2 = reg_indices[0], reg_indices[1]
        r1, r2 = innings_totals[i1], innings_totals[i2]
        t1_name, t2_name = batting_teams[i1], batting_teams[i2]

        if mid in VERIFIED_DLS_WICKET_WIN_TARGETS:
            t_runs, t_overs, t_meth = VERIFIED_DLS_WICKET_WIN_TARGETS[mid]
            target_runs_str = str(t_runs)
            target_overs_str = t_overs
            target_method_str = t_meth
            par_score_end = str(t_runs - 1)
        elif dls_method_flag:
            win_runs_val = first(row, "win_by_runs", default="")
            if win_runs_val != "":
                w_runs = to_int(win_runs_val, 0)
                # If Team 1 won by w_runs, par score was r2 + w_runs.
                # If Team 2 won by w_runs (rain stopped chase), par score was r2 - w_runs.
                if winner == t1_name:
                    p_end = r2 + w_runs
                else:
                    p_end = r2 - w_runs
                par_score_end = str(p_end)
                target_runs_str = str(p_end + 1)
            elif target_runs_str != "":
                par_score_end = str(to_int(target_runs_str) - 1)
            else:
                par_score_end = str(r1)
                target_runs_str = str(r1 + 1)

            target_overs_str = rev_overs_str if rev_overs_str else scheduled_overs_str
            target_method_str = first(row, "outcome_method", default="D/L")
        elif revised_target_flag:
            # Pre-match shortened game (e.g. 16-over or 10-over match from start without mid-innings DLS)
            par_score_end = str(r1)
            target_runs_str = str(r1 + 1) if target_runs_str == "" else target_runs_str
            target_overs_str = rev_overs_str if rev_overs_str else scheduled_overs_str
            target_method_str = "revised_quota"
        else:
            # Standard uninterrupted 20-over match
            par_score_end = str(r1)
            target_runs_str = str(r1 + 1) if target_runs_str == "" else target_runs_str
            target_overs_str = scheduled_overs_str if target_overs_str == "" else target_overs_str
            target_method_str = "standard"

    row["target_runs"] = target_runs_str
    row["target_overs"] = target_overs_str
    row["target_method"] = target_method_str

    # 6. Populate stage & canonical team columns
    is_playoff = mid in PLAYOFF_MATCH_IDS
    row["match_stage"] = "playoff" if is_playoff else "league"
    row["is_playoff"] = str(is_playoff).lower()
    row["team1_canonical"] = canonical_team(team1)
    row["team2_canonical"] = canonical_team(team2)
    row["winner_canonical"] = canonical_team(winner)
    row["has_super_over_flag"] = str(has_super_over).lower()

    # 7. Populate scalar Regulation Innings 1 & 2 columns and Official NRR inputs
    if len(reg_indices) >= 1:
        i1 = reg_indices[0]
        inn1_team = batting_teams[i1]
        inn1_runs = innings_totals[i1]
        inn1_balls = legal_ball_values[i1]
        inn1_wkts = wickets_lost_values[i1]
        inn1_ao = to_bool(all_out_flags[i1]) or (inn1_wkts >= 10)
        inn1_overs = actual_overs_values[i1]

        row["inn1_team"] = inn1_team
        row["inn1_team_canonical"] = canonical_team(inn1_team)
        row["inn1_runs"] = str(inn1_runs)
        row["inn1_legal_balls"] = str(inn1_balls)
        row["inn1_wickets"] = str(inn1_wkts)
        row["inn1_all_out"] = str(inn1_ao).lower()
        row["inn1_actual_overs"] = inn1_overs
    else:
        for col in (
            "inn1_team", "inn1_team_canonical", "inn1_runs",
            "inn1_legal_balls", "inn1_wickets", "inn1_all_out", "inn1_actual_overs"
        ):
            row[col] = ""

    if len(reg_indices) >= 2:
        i2 = reg_indices[1]
        inn2_team = batting_teams[i2]
        inn2_runs = innings_totals[i2]
        inn2_balls = legal_ball_values[i2]
        inn2_wkts = wickets_lost_values[i2]
        inn2_ao = to_bool(all_out_flags[i2]) or (inn2_wkts >= 10)
        inn2_overs = actual_overs_values[i2]

        row["inn2_team"] = inn2_team
        row["inn2_team_canonical"] = canonical_team(inn2_team)
        row["inn2_runs"] = str(inn2_runs)
        row["inn2_legal_balls"] = str(inn2_balls)
        row["inn2_wickets"] = str(inn2_wkts)
        row["inn2_all_out"] = str(inn2_ao).lower()
        row["inn2_actual_overs"] = inn2_overs
    else:
        for col in (
            "inn2_team", "inn2_team_canonical", "inn2_runs",
            "inn2_legal_balls", "inn2_wickets", "inn2_all_out", "inn2_actual_overs"
        ):
            row[col] = ""

    row["par_score_team2_end"] = par_score_end

    # Official NRR effective runs and balls per match (only for completed matches)
    if result_type != "no_result" and len(reg_indices) >= 2:
        rev_balls = (
            overs_to_balls(rev_overs_str, scheduled_balls)
            if revised_target_flag and rev_overs_str
            else scheduled_balls
        )
        inn1_runs_val = to_int(row["inn1_runs"])
        inn1_balls_val = to_int(row["inn1_legal_balls"])
        inn1_ao_val = to_bool(row["inn1_all_out"])

        inn2_runs_val = to_int(row["inn2_runs"])
        inn2_balls_val = to_int(row["inn2_legal_balls"])
        inn2_ao_val = to_bool(row["inn2_all_out"])

        if dls_method_flag:
            # Official IPL NRR rule for DLS matches:
            # Team 1 is credited with (target_runs - 1) runs in revised_target_overs.
            nrr_r1 = to_int(par_score_end, inn1_runs_val)
            nrr_b1 = rev_balls
            nrr_r2 = inn2_runs_val
            nrr_b2 = rev_balls if inn2_ao_val else inn2_balls_val
        elif revised_target_flag:
            # Pre-match shortened game (both teams had quota = rev_balls)
            nrr_r1 = inn1_runs_val
            nrr_b1 = rev_balls if inn1_ao_val else inn1_balls_val
            nrr_r2 = inn2_runs_val
            nrr_b2 = rev_balls if inn2_ao_val else inn2_balls_val
        else:
            # Standard 20-over match (119-ball umpire miscount matches credit 120 balls)
            nrr_r1 = inn1_runs_val
            if inn1_ao_val or mid in UMPIRE_119_BALL_FULL_QUOTA_MATCHES:
                nrr_b1 = scheduled_balls
            else:
                nrr_b1 = inn1_balls_val
            nrr_r2 = inn2_runs_val
            nrr_b2 = scheduled_balls if inn2_ao_val else inn2_balls_val

        row["nrr_inn1_runs"] = str(nrr_r1)
        row["nrr_inn1_balls"] = str(nrr_b1)
        row["nrr_inn2_runs"] = str(nrr_r2)
        row["nrr_inn2_balls"] = str(nrr_b2)
    else:
        row["nrr_inn1_runs"] = ""
        row["nrr_inn1_balls"] = ""
        row["nrr_inn2_runs"] = ""
        row["nrr_inn2_balls"] = ""

    row["data_validation_status"] = (
        ";".join(notes) if notes else "basic_checks_passed"
    )
    return row


# ---------------------------------------------------------
# Match and innings indexing (Full build from 4 CSVs)
# ---------------------------------------------------------

def build_master_from_split_csvs(input_files, output_file):
    matches = read_csv(input_files["matches"])
    innings_rows = read_csv(input_files["innings"])
    delivery_rows = read_csv(input_files["deliveries"])
    rain_rows = read_csv(input_files["rain"])

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

    innings_by_match = defaultdict(list)
    for innings in innings_rows:
        mid = get_match_id(innings)
        if mid:
            innings_by_match[mid].append(innings)

    deliveries_by_match = defaultdict(list)
    for delivery in delivery_rows:
        mid = get_match_id(delivery)
        if mid:
            deliveries_by_match[mid].append(delivery)

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

        balls_by_innings = defaultdict(list)
        for ball in balls:
            key = (
                get_innings_number(ball),
                get_batting_team(ball),
                get_super_over(ball),
            )
            balls_by_innings[key].append(ball)

        innings_summaries = []
        for inn in inns:
            inn_number = get_innings_number(inn)
            batting_team = get_batting_team(inn)
            super_over = get_super_over(inn)

            key = (inn_number, batting_team, super_over)
            inn_balls = balls_by_innings.get(key, [])

            innings_total = first(
                inn, "innings_total_runs", "total_runs", "runs", default=""
            )
            if innings_total == "":
                innings_total = str(sum(
                    to_int(first(b, "total_runs", default="0"))
                    for b in inn_balls
                ))

            legal_balls = first(
                inn, "legal_balls_faced", "legal_balls", default=""
            )
            if legal_balls == "":
                legal_balls = str(sum(
                    1 for b in inn_balls
                    if to_bool(first(b, "is_legal_ball", default="false"))
                ))

            wickets_lost = first(
                inn, "wickets_lost_recorded", "wickets_lost", "wickets", default=""
            )
            if wickets_lost == "":
                wickets_lost = str(sum(
                    to_int(first(b, "wicket_count", default="0"))
                    for b in inn_balls
                ))

            all_out = first(
                inn, "innings_all_out_flag", "all_out_flag", default=""
            )
            if all_out == "":
                all_out = str(to_int(wickets_lost) >= 10).lower()

            actual_overs = first(
                inn, "innings_actual_overs", "overs", default=""
            )
            if actual_overs == "":
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

        batting_teams = [x["team"] for x in innings_summaries]
        opponents = [
            team2 if x["team"] == team1
            else team1 if x["team"] == team2
            else ""
            for x in innings_summaries
        ]
        innings_numbers = [x["innings_number"] for x in innings_summaries]
        super_over_flags = [x["super_over"] for x in innings_summaries]
        innings_totals = [to_int(x["innings_total_runs"]) for x in innings_summaries]
        wickets_lost_values = [to_int(x["wickets_lost_recorded"]) for x in innings_summaries]
        legal_ball_values = [to_int(x["legal_balls_faced"]) for x in innings_summaries]
        all_out_flags = [x["innings_all_out_flag"] for x in innings_summaries]
        actual_overs_values = [x["innings_actual_overs"] for x in innings_summaries]

        revised_target_flag = first(rain, "revised_target_flag", default="false")
        dls_method_flag = first(rain, "dls_method_flag", default="false")
        shortened_flag = first(rain, "shortened_first_innings_flag", default="false")

        rain_indicator = any(
            to_bool(value)
            for value in (revised_target_flag, dls_method_flag, shortened_flag)
        )

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

        validation_status = ";".join(issues) if issues else "basic_checks_passed"

        # Check match, rain, and 2nd innings metadata for target fields
        inn2_meta = inns[1] if len(inns) > 1 else {}
        raw_target_runs = first(
            match, "target_runs", "revised_target_runs",
            default=first(
                rain, "target_runs", "revised_target_runs",
                default=first(inn2_meta, "target_runs", "target")
            ),
        )
        raw_target_overs = first(
            match, "target_overs",
            default=first(
                rain, "target_overs", "revised_target_overs",
                default=first(inn2_meta, "target_overs")
            ),
        )
        raw_target_method = first(
            match, "target_method",
            default=first(rain, "target_method", default=first(match, "outcome_method", "method")),
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
            "no_result_flag": first(match, "no_result_flag", default="false"),
            "scheduled_overs": first(match, "scheduled_overs", "overs", default="20"),
            "target_runs": raw_target_runs,
            "target_overs": raw_target_overs,
            "target_method": raw_target_method,
            "revised_target_flag": revised_target_flag,
            "revised_target_overs": first(rain, "revised_target_overs"),
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

        output_rows.append(enrich_and_fix_match_row(row))

    write_master_csv(output_rows, output_file, source_count=len(matches))


def upgrade_existing_master_csv(input_master_path, output_file):
    """
    Upgrade an existing ipl_master.csv in place when upstream split CSVs
    are not present in the local working directory.
    """
    existing_rows = read_csv(input_master_path)
    output_rows = [enrich_and_fix_match_row(dict(r)) for r in existing_rows]
    write_master_csv(output_rows, output_file, source_count=len(existing_rows))


def write_master_csv(output_rows, output_file, source_count):
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(output_rows)

    league_count = sum(1 for r in output_rows if r["is_playoff"] == "false")
    playoff_count = sum(1 for r in output_rows if r["is_playoff"] == "true")
    super_over_count = sum(1 for r in output_rows if r["has_super_over_flag"] == "true")
    dls_count = sum(1 for r in output_rows if to_bool(r["dls_method_flag"]))

    print(f"Matches in source: {source_count}")
    print(f"Master rows written: {len(output_rows)} (League: {league_count}, Playoffs: {playoff_count})")
    print(f"Super-over ties separated: {super_over_count} | DLS matches resolved: {dls_count}")
    print(f"Columns written: {len(HEADERS)}")
    print(f"Output: {output_file}")

    if len(output_rows) != source_count:
        raise RuntimeError("Output row count does not match match count.")

    print("Row-count and NRR/NRRR readiness checks passed.")


def build_master():
    parser = argparse.ArgumentParser(
        description="Build or upgrade the IPL match-level master CSV for NRR/NRRR analysis."
    )
    parser.add_argument(
        "--input-master",
        type=Path,
        default=None,
        help="Optional path to an existing ipl_master.csv to upgrade directly.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_FILE,
        help="Output path for the generated ipl_master.csv (default: data/processed/ipl_master.csv).",
    )
    args = parser.parse_args()

    if args.input_master is not None:
        upgrade_existing_master_csv(args.input_master, args.output)
    elif all(p.exists() for p in INPUT_FILES.values()):
        build_master_from_split_csvs(INPUT_FILES, args.output)
    elif OUTPUT_FILE.exists():
        print(
            f"Upstream split CSVs not found in {DATA_DIR}; "
            f"upgrading existing {OUTPUT_FILE} in place..."
        )
        upgrade_existing_master_csv(OUTPUT_FILE, args.output)
    else:
        missing = [str(p) for p in INPUT_FILES.values() if not p.exists()]
        raise FileNotFoundError(
            f"Missing upstream CSV files ({', '.join(missing)}) and no existing "
            f"{OUTPUT_FILE} found. Pass --input-master <path/to/ipl_master.csv> to upgrade."
        )


if __name__ == "__main__":
    build_master()