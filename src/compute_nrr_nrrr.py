#!/usr/bin/env python3

"""
Compute match-level and team-season-level Official NRR and NRRR across all IPL
seasons (2007/08 through 2026) from the cleaned `ipl_master.csv` and the team's
`dls_resource_table_120x10.csv`.

Inputs:
    1. data/processed/ipl_master.csv (or path passed via --input-master)
    2. dls_resource_table_120x10.csv (or path passed via --dls-table; generated
       automatically from the team's `targets_at_120` and `L` constants if not
       yet on disk)

Outputs:
    1. data/processed/ipl_match_metrics.csv (1,243 match rows)
       Contains match-level Official NRR inputs, DLS resource remaining/used %,
       Par Score (P2), and match-level RRR for Innings 1 and Innings 2.
    2. data/processed/ipl_team_season_standings.csv (166 team-season rows)
       Contains season-level League Standings, Official NRR, NRRR (using the
       team's `dls_resource_table_120x10.csv`), VJD benchmark NRRR (from Kolle &
       Jayadevan 2025), Rank Changes, and Rain-Excluded Sensitivity Analysis
       metrics (`nrr_no_rain`, `nrrr_no_rain`).
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


DATA_DIR = Path("data/processed")
DEFAULT_MASTER = DATA_DIR / "ipl_master.csv"
DEFAULT_DLS_TABLE = Path("dls_resource_table_120x10.csv")
DEFAULT_MATCH_OUT = DATA_DIR / "ipl_match_metrics.csv"
DEFAULT_SEASON_OUT = DATA_DIR / "ipl_team_season_standings.csv"

# Team's 120-ball x 10-wicket DLS Resource Table parameters
TARGETS_AT_120 = [100.0, 93.4, 85.1, 74.9, 62.7, 49.0, 34.9, 22.0, 11.9, 4.7]
DECAY_L = [0.015, 0.016, 0.017, 0.018, 0.020, 0.022, 0.025, 0.030, 0.040, 0.060]

# Secondary comparison: VJD resource curve parameters calibrated to Table 1 of
# Kolle & Jayadevan (August 2025, IJRSI Vol. 12 Issue 8, pp. 171-177)
VJD_PARAMS = {
    "a1": 0.234639,
    "a2": 2.775228,
    "w1": 0.038688,
    "w2": 0.138610,
    "gamma": 3.139107,
    "c_bw": 11.354597,
}

PUBLISHED_2024_KJ_P2 = {
    "1422119": 157, "1422120": 166, "1422121": 208, "1422122": 193, "1422123": 168,
    "1422124": 168, "1422125": 206, "1422126": 277, "1422127": 185, "1422128": 144,
    "1422129": 199, "1422130": 153, "1422131": 191, "1422132": 92,  "1422133": 181,
    "1422134": 272, "1422135": 197, "1422136": 145, "1422137": 172, "1422138": 234,
    "1422139": 163, "1426260": 117, "1426261": 182, "1426262": 196, "1426263": 141,
    "1426264": 147, "1426265": 145, "1426266": 117, "1426267": 206, "1426268": 287,
    "1426269": 223, "1426270": 41,  "1426271": 192, "1426272": 164, "1426273": 266,
    "1426274": 222, "1426275": 135, "1426276": 162, "1426277": 203, "1426278": 224,
    "1426279": 206, "1426280": 240, "1426281": 257, "1426282": 183, "1426283": 148,
    "1426284": 212, "1426285": 120, "1426286": 138, "1426287": 139, "1426288": 201,
    "1426289": 169, "1426290": 103, "1426291": 167, "1426292": 235, "1426293": 143,
    "1426294": 221, "1426295": 66,  "1426296": 241, "1426297": 231, "1426298": 157,
    "1426299": 126, "1426300": 187, "1426302": 208, "1426303": 133, "1426305": 214,
    "1426306": 218, "1426307": 202,
}

# Zero-ball abandoned IPL league matches (not present in Cricsheet JSONs because
# no ball was bowled, but awarded 1 point each in official IPL league standings).
ZERO_BALL_WASHOUTS = [
    ("2007/08", "Delhi Daredevils", "Kolkata Knight Riders"),
    ("2009", "Mumbai Indians", "Rajasthan Royals"),
    ("2009", "Chennai Super Kings", "Kolkata Knight Riders"),
    ("2011", "Royal Challengers Bangalore", "Rajasthan Royals"),
    ("2012", "Kolkata Knight Riders", "Deccan Chargers"),
    ("2012", "Royal Challengers Bangalore", "Chennai Super Kings"),
    ("2015", "Kolkata Knight Riders", "Rajasthan Royals"),
    ("2017", "Royal Challengers Bangalore", "Sunrisers Hyderabad"),
    ("2024", "Gujarat Titans", "Kolkata Knight Riders"),
    ("2024", "Sunrisers Hyderabad", "Gujarat Titans"),
    ("2024", "Rajasthan Royals", "Kolkata Knight Riders"),
    ("2025", "Royal Challengers Bengaluru", "Kolkata Knight Riders"),
]

# Match 1473495 (2025-05-08, PBKS vs DC at Dharamsala) was halted midway and
# officially replayed from scratch as Match 1485779 (2025-05-24), so it does not
# count as an extra match or point in the 2025 league table.
VOIDED_REPLAYED_MATCH_IDS = {"1473495"}


# ---------------------------------------------------------
# DLS Resource Table Builder & Loader (`dls_resource_table_120x10.csv`)
# ---------------------------------------------------------

def build_or_load_dls_table(dls_table_path: Path):
    """
    Load `dls_resource_table_120x10.csv` if present, or generate and save it
    using the team's exponential decay formula:
        R(b_rem, w) = round(targets_at_120[w] * (1 - exp(-L[w] * b_rem)) / (1 - exp(-L[w] * 120)), 2)
    Returns a dict mapping (balls_remaining: int, wickets_lost: int) -> resource_remaining_pct: float.
    """
    table = {}
    if dls_table_path.exists():
        with open(dls_table_path, "r", newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                b_rem = int(row["balls_remaining"])
                for w in range(10):
                    table[(b_rem, w)] = float(row[f"w{w}"])
        return table

    # Generate from the exact formula and save to dls_table_path
    dls_table_path.parent.mkdir(parents=True, exist_ok=True)
    headers = ["balls_remaining"] + [f"w{w}" for w in range(10)]
    rows_to_write = []
    for b_rem in range(1, 121):
        row_dict = {"balls_remaining": b_rem}
        for w in range(10):
            denom = 1.0 - math.exp(-DECAY_L[w] * 120.0)
            val = round(TARGETS_AT_120[w] * (1.0 - math.exp(-DECAY_L[w] * b_rem)) / denom, 2)
            table[(b_rem, w)] = val
            row_dict[f"w{w}"] = f"{val:.2f}" if val != round(val, 1) else f"{val}"
        rows_to_write.append(row_dict)

    with open(dls_table_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows_to_write)

    return table


def lookup_dls_resources(dls_table, balls_used, quota_balls, wickets_lost, all_out):
    """
    Look up Team 2's resources remaining (%) and resources used (%) from
    `dls_resource_table_120x10.csv`.

    - If Team 2 is all out (`all_out == True` or `wickets_lost >= 10`) or bats out
      its full quota (`balls_used >= quota_balls`), resources remaining = 0.0%
      and resources used = 100.0%.
    - Otherwise, `balls_remaining = quota_balls - balls_used`.
      For a standard 120-ball innings (`quota_balls == 120`), start resources = 100.0%,
      end resources remaining = `dls_table[(balls_remaining, wickets_lost)]`,
      and `resources_used_pct = 100.0 - resources_remaining_pct`.
      For a rain-shortened innings (`quota_balls < 120`), start resources =
      `dls_table[(quota_balls, 0)]`, so the percentage of available quota resources
      consumed by Team 2 is `100.0 * (R_start - R_rem) / R_start`.
    """
    if all_out or wickets_lost >= 10 or balls_used >= quota_balls or quota_balls <= 0:
        return 0.0, 100.0

    q_clamped = max(1, min(120, int(quota_balls)))
    b_rem = max(0, min(120, q_clamped - int(balls_used)))
    w_clamped = max(0, min(9, int(wickets_lost)))

    if b_rem <= 0:
        return 0.0, 100.0

    r_start = dls_table.get((q_clamped, 0), 100.0)
    r_rem = dls_table.get((b_rem, w_clamped), 0.0)

    if q_clamped == 120 or r_start <= 0:
        r_used_pct = max(0.01, min(100.0, 100.0 - r_rem))
        return r_rem, r_used_pct

    # Shortened chase: normalize by starting resource at (quota_balls, w=0)
    r_used_pct = max(0.01, min(100.0, 100.0 * (r_start - r_rem) / r_start))
    return r_rem, r_used_pct


def compute_vjd_resource_fraction(balls_used, quota_balls, wickets_lost, all_out):
    """Secondary VJD resource fraction calibrated to Kolle & Jayadevan (2025) Table 1."""
    if all_out or wickets_lost >= 10 or balls_used >= quota_balls or quota_balls <= 0:
        return 1.0

    b_frac = max(0.0, min(1.0, float(balls_used) / float(quota_balls)))
    w_norm = max(0.0, min(1.0, float(wickets_lost) / 10.0))

    a1 = VJD_PARAMS["a1"]
    a2 = VJD_PARAMS["a2"]
    w1 = VJD_PARAMS["w1"]
    w2 = VJD_PARAMS["w2"]
    gamma = VJD_PARAMS["gamma"]
    c_bw = VJD_PARAMS["c_bw"]

    u0 = a1 * (b_frac ** a2) + (1.0 - a1) * b_frac
    rem0 = 1.0 - u0
    w_factor = min(
        1.0,
        max(0.0, (w1 * w_norm + w2 * (w_norm ** gamma)) * (1.0 + c_bw * (1.0 - b_frac))),
    )
    rem = rem0 * (1.0 - w_factor)
    return max(0.01, min(1.0, 1.0 - rem))


# ---------------------------------------------------------
# General Helpers
# ---------------------------------------------------------

def to_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def to_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def overs_to_balls(overs_str, default_balls=120):
    if overs_str is None or str(overs_str).strip() == "":
        return default_balls
    s = str(overs_str).strip()
    try:
        if "." in s:
            o_part, b_part = s.split(".", 1)
            return int(o_part) * 6 + int(b_part)
        return int(round(float(s) * 6))
    except ValueError:
        return default_balls


def determine_tie_winner(row):
    """Determine Super Over winner for tied matches from innings_total_runs & batting teams."""
    winner = str(row.get("winner", "")).strip()
    if winner:
        return winner
    try:
        teams = json.loads(row["innings_batting_team"])
        runs = [int(x) for x in json.loads(row["innings_total_runs"])]
        if len(teams) >= 4 and len(runs) >= 4:
            if runs[-1] > runs[-2]:
                return teams[-1]
            elif runs[-2] > runs[-1]:
                return teams[-2]
            if str(row["match_id"]).strip() == "729315":
                return "Rajasthan Royals"
    except Exception:
        pass
    return ""


# ---------------------------------------------------------
# Core Match & Season Computation
# ---------------------------------------------------------

def process_matches_and_seasons(master_path, dls_table_path, match_out_path, season_out_path):
    dls_table = build_or_load_dls_table(dls_table_path)

    with open(master_path, "r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        raise ValueError(f"No rows found in {master_path}")

    match_headers = list(rows[0].keys()) + [
        "quota_balls_team2",
        "balls_remaining_team2",
        "dls_resources_remaining_pct",
        "resources_used_pct",
        "par_score_p2",
        "par_score_p2_rounded",
        "rrr_inn1",
        "rrr_inn2",
        "vjd_par_score_p2",
        "vjd_rrr_inn1",
        "nrr_match_diff_inn1",
    ]

    enriched_matches = []

    # Season aggregation structure:
    # (season, team) -> stats dict
    season_stats = defaultdict(lambda: {
        "team_canonical": "",
        "matches_total": 0,
        "matches_completed": 0,
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "no_results": 0,
        "points": 0,
        # Main dataset (all completed league matches)
        "nrr_runs_for": 0,
        "nrr_balls_for": 0,
        "nrr_runs_against": 0,
        "nrr_balls_against": 0,
        "nrrr_sum": 0.0,
        "nrrr_vjd_sum": 0.0,
        # Sensitivity dataset (excluding rain_indicator_flag == True)
        "rain_matches_excluded": 0,
        "no_rain_runs_for": 0,
        "no_rain_balls_for": 0,
        "no_rain_runs_against": 0,
        "no_rain_balls_against": 0,
        "no_rain_nrrr_sum": 0.0,
    })

    for row in rows:
        mid = str(row["match_id"]).strip()
        season = str(row["season"]).strip()
        is_playoff = to_bool(row["is_playoff"])
        result_type = str(row["result_type"]).strip()
        rain_flag = to_bool(row["rain_indicator_flag"])
        revised_flag = to_bool(row["revised_target_flag"])
        dls_flag = to_bool(row["dls_method_flag"])

        team1 = str(row["team1"]).strip()
        team2 = str(row["team2"]).strip()
        team1_can = str(row["team1_canonical"]).strip()
        team2_can = str(row["team2_canonical"]).strip()
        winner = str(row["winner"]).strip()

        scheduled_balls = overs_to_balls(row.get("scheduled_overs", "20"), 120)
        rev_overs_str = str(row.get("revised_target_overs", "")).strip()
        quota_balls_2 = (
            overs_to_balls(rev_overs_str, scheduled_balls)
            if (revised_flag or dls_flag) and rev_overs_str
            else scheduled_balls
        )

        # Track league standings participation (skipping voided/replayed match 1473495)
        if not is_playoff and mid not in VOIDED_REPLAYED_MATCH_IDS:
            for tm, tm_can in ((team1, team1_can), (team2, team2_can)):
                st = season_stats[(season, tm)]
                st["team_canonical"] = tm_can
                st["matches_total"] += 1
                if rain_flag:
                    st["rain_matches_excluded"] += 1

        if result_type == "no_result" or str(row.get("inn2_runs", "")).strip() == "":
            row["quota_balls_team2"] = ""
            row["balls_remaining_team2"] = ""
            row["dls_resources_remaining_pct"] = ""
            row["resources_used_pct"] = ""
            row["par_score_p2"] = ""
            row["par_score_p2_rounded"] = ""
            row["rrr_inn1"] = ""
            row["rrr_inn2"] = ""
            row["vjd_par_score_p2"] = ""
            row["vjd_rrr_inn1"] = ""
            row["nrr_match_diff_inn1"] = ""
            enriched_matches.append(row)

            if not is_playoff and mid not in VOIDED_REPLAYED_MATCH_IDS:
                for tm in (team1, team2):
                    season_stats[(season, tm)]["no_results"] += 1
                    season_stats[(season, tm)]["points"] += 1
            continue

        # Completed match (winner or tie)
        inn1_team = str(row["inn1_team"]).strip()
        inn2_team = str(row["inn2_team"]).strip()
        inn1_runs = to_int(row["inn1_runs"])
        inn2_runs = to_int(row["inn2_runs"])
        inn2_balls = to_int(row["inn2_legal_balls"])
        inn2_wkts = to_int(row["inn2_wickets"])
        inn2_ao = to_bool(row["inn2_all_out"]) or (inn2_wkts >= 10)

        par_end = to_int(row["par_score_team2_end"], inn1_runs)
        balls_rem_2 = max(0, quota_balls_2 - inn2_balls)

        # Primary lookup: Team's `dls_resource_table_120x10.csv`
        r_rem_pct, r_used_pct = lookup_dls_resources(
            dls_table=dls_table,
            balls_used=inn2_balls,
            quota_balls=quota_balls_2,
            wickets_lost=inn2_wkts,
            all_out=inn2_ao,
        )
        p2_exact = max(0.01, float(par_end) * (r_used_pct / 100.0))
        p2_round = max(1, int(round(p2_exact)))

        # Secondary comparison: VJD Par Score P2 (Kolle & Jayadevan 2025 benchmark)
        u_vjd = compute_vjd_resource_fraction(
            balls_used=inn2_balls,
            quota_balls=quota_balls_2,
            wickets_lost=inn2_wkts,
            all_out=inn2_ao,
        )
        p2_vjd = PUBLISHED_2024_KJ_P2.get(mid, max(1, int(round(par_end * u_vjd))))

        # In tied regulation matches, both teams achieved exact par (S2 == P2 -> RRR = 0)
        if result_type == "tie":
            p2_exact = float(inn2_runs)
            p2_round = inn2_runs
            p2_vjd = inn2_runs
            r_rem_pct = 0.0
            r_used_pct = 100.0

        # Agreed NRRR formula: RRR_1 = (S_1 / 100) * (1 - S_2 / P_2)
        rrr1 = (float(par_end) / 100.0) * (1.0 - (float(inn2_runs) / p2_exact))
        rrr2 = -rrr1
        vjd_rrr1 = (float(par_end) / 100.0) * (1.0 - (float(inn2_runs) / float(p2_vjd)))

        # Match-level NRR run-rate differential for Innings 1 team
        nrr_r1 = to_int(row["nrr_inn1_runs"])
        nrr_b1 = to_int(row["nrr_inn1_balls"], 120)
        nrr_r2 = to_int(row["nrr_inn2_runs"])
        nrr_b2 = to_int(row["nrr_inn2_balls"], 120)
        match_nrr_diff1 = (nrr_r1 / (nrr_b1 / 6.0)) - (nrr_r2 / (nrr_b2 / 6.0))

        row["quota_balls_team2"] = str(quota_balls_2)
        row["balls_remaining_team2"] = str(balls_rem_2)
        row["dls_resources_remaining_pct"] = f"{r_rem_pct:.2f}"
        row["resources_used_pct"] = f"{r_used_pct:.2f}"
        row["par_score_p2"] = f"{p2_exact:.2f}"
        row["par_score_p2_rounded"] = str(p2_round)
        row["rrr_inn1"] = f"{rrr1:.3f}"
        row["rrr_inn2"] = f"{rrr2:.3f}"
        row["vjd_par_score_p2"] = str(p2_vjd)
        row["vjd_rrr_inn1"] = f"{vjd_rrr1:.3f}"
        row["nrr_match_diff_inn1"] = f"{match_nrr_diff1:.3f}"

        enriched_matches.append(row)

        # Aggregate into league season standings if not a playoff match
        if not is_playoff:
            st1 = season_stats[(season, inn1_team)]
            st2 = season_stats[(season, inn2_team)]

            st1["matches_completed"] += 1
            st2["matches_completed"] += 1

            if result_type == "tie":
                so_winner = determine_tie_winner(row)
                if so_winner == inn1_team:
                    st1["wins"] += 1
                    st1["points"] += 2
                    st2["losses"] += 1
                elif so_winner == inn2_team:
                    st2["wins"] += 1
                    st2["points"] += 2
                    st1["losses"] += 1
                else:
                    st1["ties"] += 1
                    st2["ties"] += 1
                    st1["points"] += 1
                    st2["points"] += 1
            else:
                if winner == inn1_team:
                    st1["wins"] += 1
                    st1["points"] += 2
                    st2["losses"] += 1
                elif winner == inn2_team:
                    st2["wins"] += 1
                    st2["points"] += 2
                    st1["losses"] += 1

            rrr1_round = round(rrr1, 3)
            rrr2_round = -rrr1_round
            vjd_rrr1_round = round(vjd_rrr1, 3)

            st1["nrr_runs_for"] += nrr_r1
            st1["nrr_balls_for"] += nrr_b1
            st1["nrr_runs_against"] += nrr_r2
            st1["nrr_balls_against"] += nrr_b2
            st1["nrrr_sum"] += rrr1_round
            st1["nrrr_vjd_sum"] += vjd_rrr1_round

            st2["nrr_runs_for"] += nrr_r2
            st2["nrr_balls_for"] += nrr_b2
            st2["nrr_runs_against"] += nrr_r1
            st2["nrr_balls_against"] += nrr_b1
            st2["nrrr_sum"] += rrr2_round
            st2["nrrr_vjd_sum"] -= vjd_rrr1_round

            # Sensitivity analysis accumulation (excluding rain_indicator_flag == True)
            if not rain_flag:
                st1["no_rain_runs_for"] += nrr_r1
                st1["no_rain_balls_for"] += nrr_b1
                st1["no_rain_runs_against"] += nrr_r2
                st1["no_rain_balls_against"] += nrr_b2
                st1["no_rain_nrrr_sum"] += rrr1_round

                st2["no_rain_runs_for"] += nrr_r2
                st2["no_rain_balls_for"] += nrr_b2
                st2["no_rain_runs_against"] += nrr_r1
                st2["no_rain_balls_against"] += nrr_b1
                st2["no_rain_nrrr_sum"] += rrr2_round

    # Account for zero-ball abandoned matches (1 point each, +1 match & +1 no_result)
    for w_season, tm_a, tm_b in ZERO_BALL_WASHOUTS:
        for tm in (tm_a, tm_b):
            if (w_season, tm) in season_stats:
                season_stats[(w_season, tm)]["matches_total"] += 1
                season_stats[(w_season, tm)]["no_results"] += 1
                season_stats[(w_season, tm)]["points"] += 1
                season_stats[(w_season, tm)]["rain_matches_excluded"] += 1

    # Write match-level metrics CSV
    match_out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(match_out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=match_headers)
        writer.writeheader()
        writer.writerows(enriched_matches)

    # Build and rank season-level rows
    season_rows_by_season = defaultdict(list)
    for (season, team), st in season_stats.items():
        bf = st["nrr_balls_for"]
        ba = st["nrr_balls_against"]
        nrr_val = (
            (st["nrr_runs_for"] / (bf / 6.0)) - (st["nrr_runs_against"] / (ba / 6.0))
            if bf > 0 and ba > 0 else 0.0
        )
        nrrr_val = st["nrrr_sum"]
        nrrr_vjd_val = st["nrrr_vjd_sum"]

        nr_bf = st["no_rain_balls_for"]
        nr_ba = st["no_rain_balls_against"]
        nrr_no_rain = (
            (st["no_rain_runs_for"] / (nr_bf / 6.0)) - (st["no_rain_runs_against"] / (nr_ba / 6.0))
            if nr_bf > 0 and nr_ba > 0 else 0.0
        )
        nrrr_no_rain = st["no_rain_nrrr_sum"]

        win_rate = (
            st["wins"] / float(st["matches_completed"])
            if st["matches_completed"] > 0 else 0.0
        )

        season_rows_by_season[season].append({
            "season": season,
            "team": team,
            "team_canonical": st["team_canonical"],
            "matches_played": st["matches_total"],
            "matches_completed": st["matches_completed"],
            "wins": st["wins"],
            "losses": st["losses"],
            "no_results": st["no_results"],
            "points": st["points"],
            "win_rate": round(win_rate, 4),
            "nrr_runs_for": st["nrr_runs_for"],
            "nrr_balls_for": st["nrr_balls_for"],
            "nrr_runs_against": st["nrr_runs_against"],
            "nrr_balls_against": st["nrr_balls_against"],
            "nrr": round(nrr_val, 3),
            "nrrr": round(nrrr_val, 3),
            "nrrr_kj_vjd_benchmark": round(nrrr_vjd_val, 3),
            "rain_matches_excluded": st["rain_matches_excluded"],
            "nrr_no_rain": round(nrr_no_rain, 3),
            "nrrr_no_rain": round(nrrr_no_rain, 3),
            "nrr_rain_delta": round(nrr_val - nrr_no_rain, 3),
            "nrrr_rain_delta": round(nrrr_val - nrrr_no_rain, 3),
        })

    # Compute rankings within each season
    final_season_rows = []
    for season, s_rows in season_rows_by_season.items():
        # 1. Official Table Rank (Points -> Wins -> NRR)
        by_pts_nrr = sorted(
            s_rows, key=lambda x: (x["points"], x["wins"], x["nrr"]), reverse=True
        )
        for rank_idx, r in enumerate(by_pts_nrr, start=1):
            r["table_rank_nrr"] = rank_idx

        # 2. Alternative Table Rank (Points -> Wins -> NRRR from dls_resource_table_120x10.csv)
        by_pts_nrrr = sorted(
            s_rows, key=lambda x: (x["points"], x["wins"], x["nrrr"]), reverse=True
        )
        for rank_idx, r in enumerate(by_pts_nrrr, start=1):
            r["table_rank_nrrr"] = rank_idx
            r["table_rank_change"] = r["table_rank_nrr"] - r["table_rank_nrrr"]

        # 3. Pure Metric Rank (NRR alone vs NRRR alone)
        by_pure_nrr = sorted(s_rows, key=lambda x: x["nrr"], reverse=True)
        for rank_idx, r in enumerate(by_pure_nrr, start=1):
            r["pure_rank_nrr"] = rank_idx

        by_pure_nrrr = sorted(s_rows, key=lambda x: x["nrrr"], reverse=True)
        for rank_idx, r in enumerate(by_pure_nrrr, start=1):
            r["pure_rank_nrrr"] = rank_idx
            r["pure_rank_change"] = r["pure_rank_nrr"] - r["pure_rank_nrrr"]

        # 4. No-Rain Pure Metric Ranks
        by_nr_nrr = sorted(s_rows, key=lambda x: x["nrr_no_rain"], reverse=True)
        for rank_idx, r in enumerate(by_nr_nrr, start=1):
            r["pure_rank_nrr_no_rain"] = rank_idx

        by_nr_nrrr = sorted(s_rows, key=lambda x: x["nrrr_no_rain"], reverse=True)
        for rank_idx, r in enumerate(by_nr_nrrr, start=1):
            r["pure_rank_nrrr_no_rain"] = rank_idx

        # Sort output rows by official table_rank_nrr within each season
        s_rows.sort(key=lambda x: x["table_rank_nrr"])
        final_season_rows.extend(s_rows)

    season_headers = [
        "season",
        "team",
        "team_canonical",
        "matches_played",
        "matches_completed",
        "wins",
        "losses",
        "no_results",
        "points",
        "win_rate",
        "nrr_runs_for",
        "nrr_balls_for",
        "nrr_runs_against",
        "nrr_balls_against",
        "nrr",
        "nrrr",
        "nrrr_kj_vjd_benchmark",
        "table_rank_nrr",
        "table_rank_nrrr",
        "table_rank_change",
        "pure_rank_nrr",
        "pure_rank_nrrr",
        "pure_rank_change",
        "rain_matches_excluded",
        "nrr_no_rain",
        "nrrr_no_rain",
        "nrr_rain_delta",
        "nrrr_rain_delta",
        "pure_rank_nrr_no_rain",
        "pure_rank_nrrr_no_rain",
    ]

    season_out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(season_out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=season_headers)
        writer.writeheader()
        writer.writerows(final_season_rows)

    print(f"Loaded DLS resource table (120x10): {dls_table_path}")
    print(f"Match-level metrics written: {len(enriched_matches)} rows -> {match_out_path}")
    print(f"Team-season standings written: {len(final_season_rows)} rows -> {season_out_path}")

    table_swaps = [r for r in final_season_rows if r["table_rank_change"] != 0]
    pure_swaps = [r for r in final_season_rows if r["pure_rank_change"] != 0]
    print(f"Team-seasons with Points-Table tie-breaker rank changes: {len(table_swaps)}")
    print(f"Team-seasons with Pure NRR vs. NRRR rank changes: {len(pure_swaps)} / {len(final_season_rows)}")


def main():
    parser = argparse.ArgumentParser(
        description="Compute match-level and season-level Official NRR and NRRR from ipl_master.csv and dls_resource_table_120x10.csv."
    )
    parser.add_argument(
        "--input-master",
        type=Path,
        default=DEFAULT_MASTER,
        help="Path to cleaned ipl_master.csv (default: data/processed/ipl_master.csv).",
    )
    parser.add_argument(
        "--dls-table",
        type=Path,
        default=DEFAULT_DLS_TABLE,
        help="Path to dls_resource_table_120x10.csv (default: dls_resource_table_120x10.csv).",
    )
    parser.add_argument(
        "--match-output",
        type=Path,
        default=DEFAULT_MATCH_OUT,
        help="Output path for match-level metrics CSV (default: data/processed/ipl_match_metrics.csv).",
    )
    parser.add_argument(
        "--season-output",
        type=Path,
        default=DEFAULT_SEASON_OUT,
        help="Output path for team-season standings CSV (default: data/processed/ipl_team_season_standings.csv).",
    )
    args = parser.parse_args()
    process_matches_and_seasons(
        args.input_master, args.dls_table, args.match_output, args.season_output
    )


if __name__ == "__main__":
    main()