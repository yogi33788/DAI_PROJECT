#!/usr/bin/env python3
"""Build IPL match, innings, and delivery CSVs from a Cricsheet IPL JSON ZIP.

Usage:
    python src/build_ipl_datasets.py data/raw/ipl_male_json.zip data/processed

Raw legal-ball counts are exported. Apply official IPL NRR rules separately:
all-out innings and interrupted/revised matches require special handling.
"""
import csv
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path


def as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def event_name(event):
    if isinstance(event, dict):
        return event.get("name", "")
    return str(event or "")


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(
            "Usage: python src/build_ipl_datasets.py INPUT.zip [OUTPUT_DIR]"
        )
    zip_path = Path(sys.argv[1]).expanduser()
    out_dir = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else Path("data/processed")
    if not zip_path.is_file():
        raise SystemExit(f"Input ZIP not found: {zip_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    matches, innings_rows, deliveries = [], [], []
    errors = []
    with zipfile.ZipFile(zip_path) as archive:
        json_files = [n for n in archive.namelist() if n.lower().endswith(".json")]
        for filename in json_files:
            try:
                data = json.loads(archive.read(filename))
                info = data.get("info", {})
                ev = event_name(info.get("event"))
                # The input is expected to be the IPL-only archive; still reject
                # explicit non-IPL events if a mixed archive is accidentally used.
                if ev and ev != "Indian Premier League":
                    continue

                match_id = Path(filename).stem
                dates = info.get("dates") or []
                date = str(dates[0]) if dates else ""
                teams = info.get("teams") or []
                outcome = info.get("outcome") or {}
                by = outcome.get("by") or {}
                toss = info.get("toss") or {}
                winner = outcome.get("winner", "")
                result_text = str(outcome.get("result", "")).lower()
                method = str(outcome.get("method", "")).lower()

                if winner:
                    result_type = "winner"
                elif "no result" in result_text:
                    result_type = "no_result"
                elif "tie" in result_text or "tie" in method:
                    result_type = "tie"
                elif outcome:
                    result_type = "other"
                else:
                    result_type = "no_winner_recorded"

                matches.append({
                    "match_id": match_id,
                    "date": date,
                    "season": str(info.get("season", "")),
                    "event": ev or "Indian Premier League",
                    "venue": info.get("venue", ""),
                    "city": info.get("city", ""),
                    "team1": teams[0] if len(teams) > 0 else "",
                    "team2": teams[1] if len(teams) > 1 else "",
                    "toss_winner": toss.get("winner", ""),
                    "toss_decision": toss.get("decision", ""),
                    "winner": winner,
                    "result_type": result_type,
                    "outcome_method": outcome.get("method", ""),
                    "outcome_result": outcome.get("result", ""),
                    "win_by_runs": by.get("runs", ""),
                    "win_by_wickets": by.get("wickets", ""),
                    "scheduled_overs": info.get("overs", 20),
                    "balls_per_over": info.get("balls_per_over", 6),
                    "source_file": Path(filename).name,
                })

                for innings_num, innings in enumerate(data.get("innings", []), start=1):
                    team = innings.get("team", "")
                    super_over = bool(innings.get("super_over", False))
                    target = innings.get("target") or {}
                    total_runs = batter_runs_sum = extras_sum = 0
                    legal_balls = deliveries_count = wickets_lost = 0
                    wides_runs = noballs_runs = byes_runs = legbyes_runs = penalty_extras = 0

                    for over in innings.get("overs", []):
                        over_num = as_int(over.get("over"))
                        for delivery_idx, delivery in enumerate(over.get("deliveries", []), start=1):
                            runs = delivery.get("runs") or {}
                            extras = delivery.get("extras") or {}
                            batter_runs = as_int(runs.get("batter"))
                            extras_runs = as_int(runs.get("extras"))
                            delivery_runs = as_int(runs.get("total"))
                            is_legal = "wides" not in extras and "noballs" not in extras
                            wickets = delivery.get("wickets") or []
                            wickets_lost += len(wickets)
                            total_runs += delivery_runs
                            batter_runs_sum += batter_runs
                            extras_sum += extras_runs
                            deliveries_count += 1
                            legal_balls += int(is_legal)
                            wides_runs += as_int(extras.get("wides"))
                            noballs_runs += as_int(extras.get("noballs"))
                            byes_runs += as_int(extras.get("byes"))
                            legbyes_runs += as_int(extras.get("legbyes"))
                            penalty_extras += as_int(extras.get("penalty"))
                            deliveries.append({
                                "match_id": match_id,
                                "date": date,
                                "season": str(info.get("season", "")),
                                "innings_number": innings_num,
                                "team": team,
                                "super_over": super_over,
                                "over_number_zero_based": over_num,
                                "delivery_index_in_over": delivery_idx,
                                "batter": delivery.get("batter", ""),
                                "bowler": delivery.get("bowler", ""),
                                "batter_runs": batter_runs,
                                "extras_runs": extras_runs,
                                "total_runs": delivery_runs,
                                "is_legal_ball": is_legal,
                                "wicket_count": len(wickets),
                                "wicket_details": "; ".join(
                                    f"{w.get('player_out', '')}:{w.get('kind', '')}"
                                    for w in wickets
                                ),
                            })

                    innings_penalty = innings.get("penalty_runs", 0)
                    if isinstance(innings_penalty, dict):
                        innings_penalty = innings_penalty.get("total", 0)
                    innings_penalty = as_int(innings_penalty)
                    total_runs += innings_penalty
                    opponent = next((t for t in teams if t != team), "")
                    innings_rows.append({
                        "match_id": match_id,
                        "date": date,
                        "season": str(info.get("season", "")),
                        "innings_number": innings_num,
                        "team": team,
                        "opponent": opponent,
                        "super_over": super_over,
                        "runs_scored": total_runs,
                        "batter_runs": batter_runs_sum,
                        "delivery_extras_runs": extras_sum,
                        "innings_penalty_runs": innings_penalty,
                        "wickets_lost_recorded": wickets_lost,
                        "legal_balls_faced": legal_balls,
                        "deliveries_including_illegal": deliveries_count,
                        "wides_runs": wides_runs,
                        "no_ball_runs": noballs_runs,
                        "byes_runs": byes_runs,
                        "legbyes_runs": legbyes_runs,
                        "penalty_extras_runs": penalty_extras,
                        "scheduled_overs": info.get("overs", 20),
                        "balls_per_over": info.get("balls_per_over", 6),
                        "target_runs": target.get("runs", ""),
                        "target_overs": target.get("overs", ""),
                        "target_method": target.get("method", ""),
                        "source_file": Path(filename).name,
                    })
            except Exception as exc:
                errors.append((filename, repr(exc)))

    matches.sort(key=lambda r: (r["date"], r["match_id"]))
    innings_rows.sort(key=lambda r: (r["date"], r["match_id"], r["innings_number"]))
    deliveries.sort(key=lambda r: (
        r["date"], r["match_id"], r["innings_number"],
        r["over_number_zero_based"], r["delivery_index_in_over"]
    ))
    write_csv(out_dir / "ipl_matches.csv", matches)
    write_csv(out_dir / "ipl_innings.csv", innings_rows)
    write_csv(out_dir / "ipl_deliveries.csv", deliveries)

    print(f"JSON files in archive: {len(json_files)}")
    print(f"Matches processed: {len(matches)}")
    print(f"Innings processed: {len(innings_rows)}")
    print(f"Delivery rows: {len(deliveries)}")
    print("Matches by season:")
    for season, count in sorted(Counter(r["season"] for r in matches).items()):
        print(f"  {season}: {count}")
    print(f"Errors: {len(errors)}")
    if errors:
        print("First errors:", errors[:10])
    print(f"CSV files saved to: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
