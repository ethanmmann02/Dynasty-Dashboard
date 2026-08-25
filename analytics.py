"""
Analytics - Nicos Dynasty League
-----------------------------------
Everything that isn't a raw Sleeper API call: power rankings, season
history (with PPG+/All-Play%/Seed/Champion/Runner-Up), head-to-head,
rivalry index, streaks, top scores, transactions, and the offseason
roster-diff used on Player Profile.
"""

import functools
import pandas as pd
import streamlit as st

import sleeper_api as api

POWER_WEIGHTS = {
    "overall_record": 0.30,
    "overall_ppg": 0.22,
    "last5_record": 0.18,
    "last5_ppg": 0.12,
    "last3_record": 0.10,
    "last3_ppg": 0.08,
}


# ---------------------------------------------------------------------
# Home tab power rankings (current, in-progress season only)
# ---------------------------------------------------------------------
@st.cache_data(ttl=60 * 15, show_spinner=False)
def get_weekly_results(league_id: str, weeks: list) -> pd.DataFrame:
    rows = []
    for wk in weeks:
        try:
            matchups = api.get_matchups(league_id, wk)
        except Exception:
            continue
        if not matchups:
            continue
        by_matchup = {}
        for m in matchups:
            mid = m.get("matchup_id")
            if mid is None:
                continue
            by_matchup.setdefault(mid, []).append(m)
        for mid, pair in by_matchup.items():
            if len(pair) != 2:
                continue
            a, b = pair
            pa, pb = a.get("points", 0) or 0, b.get("points", 0) or 0
            res_a = "W" if pa > pb else ("L" if pb > pa else "T")
            res_b = "W" if pb > pa else ("L" if pa > pb else "T")
            rows.append({"week": wk, "roster_id": a["roster_id"], "points": pa, "result": res_a})
            rows.append({"week": wk, "roster_id": b["roster_id"], "points": pb, "result": res_b})
    return pd.DataFrame(rows)


def _record_and_ppg(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["roster_id", "win_pct", "ppg"])
    grp = df.groupby("roster_id")
    wins = grp["result"].apply(lambda s: (s == "W").sum())
    ties = grp["result"].apply(lambda s: (s == "T").sum())
    games = grp["result"].count()
    ppg = grp["points"].mean()
    return pd.DataFrame(
        {"roster_id": wins.index, "win_pct": ((wins + ties * 0.5) / games).values, "ppg": ppg.values}
    )


def compute_power_rankings(weekly_df: pd.DataFrame, owner_map: dict, through_week: int) -> pd.DataFrame:
    season_df = weekly_df[weekly_df["week"] <= through_week]
    if season_df.empty:
        return pd.DataFrame()

    roster_ids = sorted(season_df["roster_id"].unique())
    overall = _record_and_ppg(season_df).set_index("roster_id")
    last5_weeks = sorted(season_df["week"].unique())[-5:]
    last3_weeks = sorted(season_df["week"].unique())[-3:]
    last5 = _record_and_ppg(season_df[season_df["week"].isin(last5_weeks)]).set_index("roster_id")
    last3 = _record_and_ppg(season_df[season_df["week"].isin(last3_weeks)]).set_index("roster_id")

    def norm(series: pd.Series) -> pd.Series:
        if series.max() == series.min():
            return pd.Series(1.0, index=series.index)
        return (series - series.min()) / (series.max() - series.min())

    rows = []
    for rid in roster_ids:
        o = overall.loc[rid] if rid in overall.index else pd.Series({"win_pct": 0, "ppg": 0})
        l5 = last5.loc[rid] if rid in last5.index else pd.Series({"win_pct": 0, "ppg": 0})
        l3 = last3.loc[rid] if rid in last3.index else pd.Series({"win_pct": 0, "ppg": 0})
        tw = season_df[season_df["roster_id"] == rid]
        wins = int((tw["result"] == "W").sum())
        losses = int((tw["result"] == "L").sum())
        l5_w = int((tw[tw["week"].isin(last5_weeks)]["result"] == "W").sum())
        l5_l = int((tw[tw["week"].isin(last5_weeks)]["result"] == "L").sum())
        l3_w = int((tw[tw["week"].isin(last3_weeks)]["result"] == "W").sum())
        l3_l = int((tw[tw["week"].isin(last3_weeks)]["result"] == "L").sum())
        rows.append(
            {
                "roster_id": rid, "Team": owner_map.get(rid, f"Roster {rid}"),
                "Record": f"{wins}-{losses}", "PPG": round(o["ppg"], 1),
                "L5": f"{l5_w}-{l5_l}", "L5 PPG": round(l5["ppg"], 1),
                "L3": f"{l3_w}-{l3_l}", "L3 PPG": round(l3["ppg"], 1),
                "overall_win_pct": o["win_pct"], "overall_ppg": o["ppg"],
                "last5_win_pct": l5["win_pct"], "last5_ppg": l5["ppg"],
                "last3_win_pct": l3["win_pct"], "last3_ppg": l3["ppg"],
            }
        )
    df = pd.DataFrame(rows)
    df["overall_record_n"] = norm(df["overall_win_pct"])
    df["overall_ppg_n"] = norm(df["overall_ppg"])
    df["last5_record_n"] = norm(df["last5_win_pct"])
    df["last5_ppg_n"] = norm(df["last5_ppg"])
    df["last3_record_n"] = norm(df["last3_win_pct"])
    df["last3_ppg_n"] = norm(df["last3_ppg"])
    df["Power Score"] = (
        df["overall_record_n"] * POWER_WEIGHTS["overall_record"]
        + df["overall_ppg_n"] * POWER_WEIGHTS["overall_ppg"]
        + df["last5_record_n"] * POWER_WEIGHTS["last5_record"]
        + df["last5_ppg_n"] * POWER_WEIGHTS["last5_ppg"]
        + df["last3_record_n"] * POWER_WEIGHTS["last3_record"]
        + df["last3_ppg_n"] * POWER_WEIGHTS["last3_ppg"]
    ) * 100
    df = df.sort_values("Power Score", ascending=False).reset_index(drop=True)
    df.insert(0, "Rank", range(1, len(df) + 1))
    return df


# ---------------------------------------------------------------------
# Divisions
# ---------------------------------------------------------------------
def get_division_map(league: dict, rosters: list) -> dict:
    """roster_id -> division name, or None if this league has no divisions configured."""
    n_divisions = league.get("settings", {}).get("divisions", 0) or 0
    if not n_divisions:
        return {r["roster_id"]: None for r in rosters}
    metadata = league.get("metadata", {}) or {}
    names = {i: metadata.get(f"division_{i}", f"Division {i}") for i in range(1, n_divisions + 1)}
    return {r["roster_id"]: names.get(r.get("settings", {}).get("division"), None) for r in rosters}


def filter_real_bracket_matches(bracket: list) -> list:
    """
    Sleeper's winners_bracket includes placement games (5th place, etc)
    in the same JSON as the real championship path - e.g. the two
    round-1 losers often get paired into a consolation game that looks
    like a normal bracket match but isn't. Trace backward from the
    championship match (p == 1) through t1_from/t2_from "w" references
    to find only the matches that actually determine who plays for the
    title; drop everything else.
    """
    if not bracket:
        return []
    by_id = {m["m"]: m for m in bracket if "m" in m}
    championship = next((m for m in bracket if m.get("p") == 1), None)
    if championship is None or championship.get("m") not in by_id:
        return bracket  # can't identify the real path, safer to show everything than nothing

    reachable = set()
    stack = [championship["m"]]
    while stack:
        mid = stack.pop()
        if mid in reachable or mid not in by_id:
            continue
        reachable.add(mid)
        m = by_id[mid]
        for side in ("t1_from", "t2_from"):
            src = m.get(side) or {}
            if src.get("w") is not None and src["w"] in by_id:
                stack.append(src["w"])
    return [m for m in bracket if m.get("m") in reachable]


def _is_real_bracket_match(m: dict) -> bool:
    """
    True if this bracket match is on the actual path to the championship:
    either a directly-seeded round-1 game, or fed by the WINNER of a
    previous round (t{n}_from == {"w": match_id}). False for
    placement/consolation games (3rd place, 5th place, etc), which are
    fed by the LOSER of a previous round (t{n}_from == {"l": match_id}) -
    those involve teams already eliminated and shouldn't show up as
    "playoff games" anywhere.
    """
    for side in ("t1", "t2"):
        src = m.get(f"{side}_from")
        if src and src.get("l") is not None:
            return False
    return True


# ---------------------------------------------------------------------
# Cross-season weekly history (regular season + playoffs, tagged), with
# full opponent identity - the single source of truth for career
# stats, H2H, rivalries, streaks, and top scores.
# ---------------------------------------------------------------------
@st.cache_data(ttl=60 * 30, show_spinner=False)
def build_full_weekly_history() -> pd.DataFrame:
    rows = []
    for season in api.ALL_SEASONS:
        league_id = api.SEASON_LEAGUE_IDS[season]
        try:
            league = api.get_league(league_id)
            rosters = api.get_rosters(league_id)
            users = api.get_users(league_id)
        except Exception:
            continue

        owner_map = api.build_owner_map(users, rosters)
        owner_id_map = api.build_owner_id_map(users, rosters)
        playoff_week_start = league.get("settings", {}).get("playoff_week_start", 15)
        last_week_played = league.get("settings", {}).get("leg") or (playoff_week_start + 2)
        weeks = list(range(1, last_week_played + 1))

        # Only games that are an actual winners-bracket matchup count as
        # "playoff" - anyone eliminated in round 1 still plays games in
        # the following weeks (placement/toilet-bowl games), and those
        # aren't real playoff games. Build week -> set of legit
        # {roster_id, roster_id} pairs from the bracket, keyed by the
        # week each round falls on (round r -> playoff_week_start + r - 1).
        valid_playoff_pairs = {}
        try:
            bracket = filter_real_bracket_matches(api.get_winners_bracket(league_id))
            for m in bracket:
                t1, t2, r = m.get("t1"), m.get("t2"), m.get("r")
                if t1 is None or t2 is None or r is None:
                    continue
                if not _is_real_bracket_match(m):
                    continue
                wk_for_round = playoff_week_start + (r - 1)
                valid_playoff_pairs.setdefault(wk_for_round, set()).add(frozenset({t1, t2}))
        except Exception:
            pass

        for wk in weeks:
            try:
                matchups = api.get_matchups(league_id, wk)
            except Exception:
                continue
            if not matchups:
                continue
            by_matchup = {}
            for m in matchups:
                mid = m.get("matchup_id")
                if mid is None:
                    continue
                by_matchup.setdefault(mid, []).append(m)

            is_playoff_week = wk >= playoff_week_start
            for mid, pair in by_matchup.items():
                if len(pair) != 2:
                    continue
                a, b = pair
                if is_playoff_week:
                    pair_key = frozenset({a["roster_id"], b["roster_id"]})
                    if pair_key not in valid_playoff_pairs.get(wk, set()):
                        continue  # placement/consolation game - not tracked
                    is_playoff = True
                else:
                    is_playoff = False

                pa, pb = a.get("points", 0) or 0, b.get("points", 0) or 0
                res_a = "W" if pa > pb else ("L" if pb > pa else "T")
                res_b = "W" if pb > pa else ("L" if pa > pb else "T")
                for me, opp, my_pts, opp_pts, res in (
                    (a, b, pa, pb, res_a), (b, a, pb, pa, res_b),
                ):
                    rows.append(
                        {
                            "season": season, "week": wk, "is_playoff": is_playoff,
                            "roster_id": me["roster_id"], "owner_id": owner_id_map.get(me["roster_id"]),
                            "Team": owner_map.get(me["roster_id"], "Unknown"),
                            "opp_roster_id": opp["roster_id"], "opp_owner_id": owner_id_map.get(opp["roster_id"]),
                            "opp_Team": owner_map.get(opp["roster_id"], "Unknown"),
                            "points": my_pts, "opp_points": opp_pts, "result": res,
                        }
                    )
    return pd.DataFrame(rows)


@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_manager_directory() -> dict:
    directory = {}
    for season in api.ALL_SEASONS:
        try:
            users = api.get_users(api.SEASON_LEAGUE_IDS[season])
        except Exception:
            continue
        for u in users:
            directory[u["user_id"]] = u.get("display_name", "Unknown")
    return directory


def compute_all_play_pct(weekly_df: pd.DataFrame) -> pd.DataFrame:
    """All-play win% per roster_id/owner_id, averaged over whatever weeks are passed in (regular season only, typically)."""
    if weekly_df.empty:
        return pd.DataFrame(columns=["roster_id", "owner_id", "all_play_win_pct"])
    rows = []
    for (season, wk), grp in weekly_df.groupby(["season", "week"]):
        scores = grp[["roster_id", "owner_id", "points"]].values
        n = len(scores)
        for rid, oid, pts in scores:
            better = sum(1 for _, _, other_pts in scores if pts > other_pts)
            ties = sum(1 for _, _, other_pts in scores if pts == other_pts) - 1
            possible = n - 1
            win_pct = (better + ties * 0.5) / possible if possible else 0
            rows.append({"roster_id": rid, "owner_id": oid, "all_play_win_pct": win_pct})
    out = pd.DataFrame(rows)
    return out.groupby(["roster_id", "owner_id"], as_index=False)["all_play_win_pct"].mean()


# ---------------------------------------------------------------------
# Season history: regular season record + PPG/PPG+/All-Play% + Seed +
# Made Playoffs + Champion + Runner-Up, per team per season.
# ---------------------------------------------------------------------
@st.cache_data(ttl=60 * 30, show_spinner=False)
def build_season_history() -> pd.DataFrame:
    weekly = build_full_weekly_history()
    rows = []
    for season in api.ALL_SEASONS:
        league_id = api.SEASON_LEAGUE_IDS[season]
        try:
            league = api.get_league(league_id)
            rosters = api.get_rosters(league_id)
            users = api.get_users(league_id)
        except Exception:
            continue

        owner_map = api.build_owner_map(users, rosters)
        owner_id_map = api.build_owner_id_map(users, rosters)
        division_map = get_division_map(league, rosters)

        season_has_games = any(
            (r.get("settings", {}).get("wins", 0) + r.get("settings", {}).get("losses", 0) + r.get("settings", {}).get("ties", 0)) > 0
            for r in rosters
        )

        reg_weekly = weekly[(weekly["season"] == season) & (~weekly["is_playoff"])]
        league_avg_ppg = reg_weekly["points"].mean() if not reg_weekly.empty else None
        all_play = compute_all_play_pct(reg_weekly)

        playoff_teams = set()
        champion_roster_id = None
        runner_up_roster_id = None
        bracket = []
        real_bracket = []
        if season_has_games:  # a season with 0 games can't have real playoff results yet,
            try:              # even if Sleeper's API already returns bracket scaffolding
                bracket = api.get_winners_bracket(league_id)
            except Exception:
                bracket = []
            real_bracket = filter_real_bracket_matches(bracket)
            for m in bracket:
                # Made Playoffs uses the FULL bracket - a round-1 loser
                # still made the playoffs, they just didn't advance
                if m.get("t1") is not None:
                    playoff_teams.add(m["t1"])
                if m.get("t2") is not None:
                    playoff_teams.add(m["t2"])
            final_match = next((m for m in bracket if m.get("p") == 1), None)
            if final_match is None and bracket:
                final_round = max(m["r"] for m in bracket)
                final_match = next((m for m in bracket if m["r"] == final_round), None)
            if final_match:
                champion_roster_id = final_match.get("w")
                t1, t2, w = final_match.get("t1"), final_match.get("t2"), final_match.get("w")
                if w is not None and t1 is not None and t2 is not None:
                    runner_up_roster_id = t2 if w == t1 else t1

        # playoff W/L per roster, only real advancement games (not placement/consolation games)
        playoff_wl = {r["roster_id"]: {"w": 0, "l": 0} for r in rosters}
        for m in real_bracket:
            t1, t2, w = m.get("t1"), m.get("t2"), m.get("w")
            if t1 is None or t2 is None or w is None:
                continue
            loser = t2 if w == t1 else t1
            if w in playoff_wl:
                playoff_wl[w]["w"] += 1
            if loser in playoff_wl:
                playoff_wl[loser]["l"] += 1

        # regular season standings -> rank -> seed (only for playoff cutoff)
        playoff_cutoff = league.get("settings", {}).get("playoff_teams", 6)
        season_rows = []
        for r in rosters:
            settings = r.get("settings", {})
            wins = settings.get("wins", 0)
            losses = settings.get("losses", 0)
            ties = settings.get("ties", 0)
            fpts = settings.get("fpts", 0) + settings.get("fpts_decimal", 0) / 100
            fpts_against = settings.get("fpts_against", 0) + settings.get("fpts_against_decimal", 0) / 100
            games = wins + losses + ties
            ppg = fpts / games if games else 0.0
            ppg_plus = round((ppg / league_avg_ppg) * 100, 1) if league_avg_ppg else None
            ap_row = all_play[(all_play["roster_id"] == r["roster_id"])]
            all_play_pct = round(ap_row["all_play_win_pct"].iloc[0], 3) if not ap_row.empty else None
            wl = playoff_wl.get(r["roster_id"], {"w": 0, "l": 0})
            season_rows.append(
                {
                    "season": season, "roster_id": r["roster_id"],
                    "owner_id": owner_id_map.get(r["roster_id"]),
                    "Team": owner_map.get(r["roster_id"], "Unknown"),
                    "Division": division_map.get(r["roster_id"]),
                    "W": wins, "L": losses, "T": ties,
                    "PF": round(fpts, 1), "PA": round(fpts_against, 1), "PPG": round(ppg, 1),
                    "PPG+": ppg_plus, "All-Play %": all_play_pct,
                    "Made Playoffs": r["roster_id"] in playoff_teams,
                    "Champion": r["roster_id"] == champion_roster_id,
                    "Runner-Up": r["roster_id"] == runner_up_roster_id,
                    "Playoff Wins": wl["w"], "Playoff Losses": wl["l"],
                }
            )
        season_df = pd.DataFrame(season_rows).sort_values(["W", "PF"], ascending=[False, False]).reset_index(drop=True)
        season_df.insert(0, "Rank", range(1, len(season_df) + 1))
        if season_has_games:
            season_df["Seed"] = season_df["Rank"].apply(lambda r: r if r <= playoff_cutoff else None)
        else:
            season_df["Seed"] = None

        season_df["Division Champion"] = False
        if season_df["Division"].notna().any():
            for div_name, div_grp in season_df.groupby("Division"):
                if div_name is None:
                    continue
                winner_idx = div_grp.sort_values(["W", "PF"], ascending=[False, False]).index[0]
                season_df.loc[winner_idx, "Division Champion"] = True

        rows.append(season_df)

    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


# ---------------------------------------------------------------------
# Head-to-head + Rivalries (across ALL tracked seasons, independent of
# any season-range filter, same as Bozos)
# ---------------------------------------------------------------------
def build_h2h_summary(weekly_history: pd.DataFrame, owner_id: str) -> pd.DataFrame:
    mine = weekly_history[weekly_history["owner_id"] == owner_id]
    if mine.empty:
        return pd.DataFrame()
    rows = []
    for opp_owner_id, grp in mine.groupby("opp_owner_id"):
        if opp_owner_id is None:
            continue
        gp = len(grp)
        wins = int((grp["result"] == "W").sum())
        losses = int((grp["result"] == "L").sum())
        playoff_gp = int(grp["is_playoff"].sum())
        opp_name = grp["opp_Team"].iloc[-1]
        rows.append(
            {
                "Opponent": opp_name, "opp_owner_id": opp_owner_id, "GP": gp,
                "W": wins, "L": losses, "Playoff GP": playoff_gp,
                "Avg PF": round(grp["points"].mean(), 2), "Avg PA": round(grp["opp_points"].mean(), 2),
                "Win %": round(wins / gp, 3) if gp else 0,
            }
        )
    return pd.DataFrame(rows).sort_values("GP", ascending=False).reset_index(drop=True)


def build_h2h_matrix(weekly_history: pd.DataFrame, manager_names: dict) -> pd.DataFrame:
    """owner_id x owner_id win% matrix, using real manager names as labels."""
    owner_ids = sorted(set(weekly_history["owner_id"].dropna()) | set(weekly_history["opp_owner_id"].dropna()),
                        key=lambda oid: manager_names.get(oid, "Unknown"))
    names = [manager_names.get(oid, "Unknown") for oid in owner_ids]
    matrix = pd.DataFrame(index=names, columns=names, dtype=object)
    for oid in owner_ids:
        mine = weekly_history[weekly_history["owner_id"] == oid]
        for opp_oid in owner_ids:
            if oid == opp_oid:
                continue
            vs = mine[mine["opp_owner_id"] == opp_oid]
            if vs.empty:
                continue
            wins = int((vs["result"] == "W").sum())
            gp = len(vs)
            matrix.loc[manager_names.get(oid), manager_names.get(opp_oid)] = f"{wins}-{gp - wins} ({round(wins / gp * 100)})"
    return matrix


def build_rivalry_table(weekly_history: pd.DataFrame, owner_id: str, min_games: int = 3) -> pd.DataFrame:
    """
    Rivalry Index (0-100): blends closeness (tighter avg margin scores
    higher), balance (closer to a 50/50 series scores higher), playoff
    weight (playoff meetings count extra), and volume (more games
    played scores higher, log-scaled). This is a reconstruction of the
    Bozos formula's intent, not a byte-for-byte port of its weights -
    happy to retune once you compare it side by side with Bozos.
    """
    mine = weekly_history[weekly_history["owner_id"] == owner_id]
    if mine.empty:
        return pd.DataFrame()
    rows = []
    for opp_owner_id, grp in mine.groupby("opp_owner_id"):
        if opp_owner_id is None:
            continue
        gp = len(grp)
        if gp < min_games:
            continue
        wins = int((grp["result"] == "W").sum())
        losses = gp - wins
        playoff_gp = int(grp["is_playoff"].sum())
        margins = (grp["points"] - grp["opp_points"]).abs()
        close_games = int((margins <= 10).sum())
        blowouts = int((margins >= 30).sum())
        avg_combined = round((grp["points"] + grp["opp_points"]).mean(), 2)

        balance = 1 - abs((wins / gp) - 0.5) * 2  # 1.0 = perfectly even series
        closeness = 1 - min(margins.mean() / 40, 1)  # tighter avg margin -> closer to 1
        volume = min(gp / 15, 1)
        playoff_weight = min(playoff_gp / max(gp, 1), 1)

        rivalry_index = round(
            (balance * 35 + closeness * 30 + volume * 20 + playoff_weight * 15), 1
        )
        rows.append(
            {
                "Rival": grp["opp_Team"].iloc[-1], "GP": gp, "Playoff GP": playoff_gp,
                "W": wins, "L": losses, "Close Games": close_games, "Blowouts": blowouts,
                "Avg Combined Score": avg_combined, "Rivalry Index": rivalry_index,
            }
        )
    return pd.DataFrame(rows).sort_values("Rivalry Index", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------
# Streaks + top single-week scores
# ---------------------------------------------------------------------
def build_streaks(weekly_history: pd.DataFrame, manager_names: dict) -> pd.DataFrame:
    rows = []
    for oid, grp in weekly_history.groupby("owner_id"):
        if oid is None:
            continue
        grp = grp.sort_values(["season", "week"])
        longest_win = longest_loss = cur_win = cur_loss = 0
        for res in grp["result"]:
            if res == "W":
                cur_win += 1
                cur_loss = 0
            elif res == "L":
                cur_loss += 1
                cur_win = 0
            else:
                cur_win = cur_loss = 0
            longest_win = max(longest_win, cur_win)
            longest_loss = max(longest_loss, cur_loss)
        rows.append({"Player": manager_names.get(oid, "Unknown"), "Longest Win Streak": longest_win, "Longest Loss Streak": longest_loss})
    return pd.DataFrame(rows).sort_values(["Longest Win Streak", "Longest Loss Streak"], ascending=False).reset_index(drop=True)


def build_top_scores(weekly_history: pd.DataFrame, owner_id: str = None, n: int = 15) -> pd.DataFrame:
    df = weekly_history if owner_id is None else weekly_history[weekly_history["owner_id"] == owner_id]
    if df.empty:
        return pd.DataFrame()
    out = df[["season", "week", "Team", "opp_Team", "points", "opp_points"]].rename(
        columns={"season": "Season", "week": "Week", "Team": "Player", "opp_Team": "Opponent", "points": "Score", "opp_points": "Opp Score"}
    )
    return out.sort_values("Score", ascending=False).head(n).reset_index(drop=True)


# ---------------------------------------------------------------------
# League History table (multi-season compare) + League-wide rivalries
# + colored H2H heatmap + drafted-rookie lookup
# ---------------------------------------------------------------------
def build_league_history_table(selected_seasons: list, season_history: pd.DataFrame, weekly_history: pd.DataFrame, manager_names: dict) -> pd.DataFrame:
    """
    Richer League History comparison table: Player, Seasons, Games,
    Avg PPG (games-weighted, not season-weighted - a season with 0
    games played contributes 0 games and 0 points, not a 0 PPG season
    dragging the average down), Avg PPG+, Avg All-Play%, Total Points,
    W, L, Playoff Apps, Championships, Runner-Ups.
    """
    hist_slice = season_history[season_history["season"].isin(selected_seasons)]
    weekly_slice = weekly_history[weekly_history["season"].isin(selected_seasons) & (~weekly_history["is_playoff"])]
    league_avg_ppg = weekly_slice["points"].mean() if not weekly_slice.empty else None
    all_play = compute_all_play_pct(weekly_slice)

    rows = []
    for oid, grp in hist_slice.groupby("owner_id"):
        if oid is None:
            continue
        games = int((grp["W"] + grp["L"] + grp["T"]).sum())
        total_pf = round(grp["PF"].sum(), 2)
        avg_ppg = round(total_pf / games, 2) if games else 0.0
        mgr_weekly = weekly_slice[weekly_slice["owner_id"] == oid]
        mgr_ppg_raw = mgr_weekly["points"].mean() if not mgr_weekly.empty else None
        avg_ppg_plus = round((mgr_ppg_raw / league_avg_ppg) * 100, 1) if league_avg_ppg and mgr_ppg_raw is not None else None
        ap_row = all_play[all_play["owner_id"] == oid]
        avg_all_play = round(ap_row["all_play_win_pct"].iloc[0], 3) if not ap_row.empty else None

        rows.append(
            {
                "Player": manager_names.get(oid, "Unknown"),
                "Seasons": len(grp), "Games": games,
                "Avg PPG": avg_ppg, "Avg PPG+": avg_ppg_plus, "Avg All-Play %": avg_all_play,
                "Total Points": total_pf, "W": int(grp["W"].sum()), "L": int(grp["L"].sum()),
                "Playoff Apps": int(grp["Made Playoffs"].sum()),
                "🏆": int(grp["Champion"].sum()), "Runner-Ups": int(grp["Runner-Up"].sum()),
            }
        )
    return pd.DataFrame(rows).sort_values(["🏆", "Total Points"], ascending=[False, False]).reset_index(drop=True)


# ---------------------------------------------------------------------
# League-wide rivalries (every pair, not just one manager's view)
# ---------------------------------------------------------------------
def build_league_wide_rivalries(weekly_history: pd.DataFrame, manager_names: dict, min_games: int = 3) -> pd.DataFrame:
    rows = []
    seen_pairs = set()
    for oid, grp in weekly_history.groupby("owner_id"):
        if oid is None:
            continue
        for opp_oid, vs in grp.groupby("opp_owner_id"):
            if opp_oid is None:
                continue
            pair = tuple(sorted([oid, opp_oid]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            gp = len(vs)
            if gp < min_games:
                continue
            a_wins = int((vs["result"] == "W").sum())
            playoff_gp = int(vs["is_playoff"].sum())
            avg_combined = round((vs["points"] + vs["opp_points"]).mean(), 2)
            margins = (vs["points"] - vs["opp_points"]).abs()
            balance = 1 - abs((a_wins / gp) - 0.5) * 2
            closeness = 1 - min(margins.mean() / 40, 1)
            volume = min(gp / 15, 1)
            playoff_weight = min(playoff_gp / max(gp, 1), 1)
            rivalry_index = round(balance * 35 + closeness * 30 + volume * 20 + playoff_weight * 15, 1)
            rows.append(
                {
                    "Team A": manager_names.get(oid, "Unknown"), "Team B": manager_names.get(opp_oid, "Unknown"),
                    "GP": gp, "Playoff GP": playoff_gp,
                    "A Wins": a_wins, "A Losses": gp - a_wins,
                    "B Wins": gp - a_wins, "B Losses": a_wins,
                    "Avg Combined Score": avg_combined, "Rivalry Index": rivalry_index,
                }
            )
    return pd.DataFrame(rows).sort_values("Rivalry Index", ascending=False).reset_index(drop=True)


def build_h2h_heatmap(weekly_history: pd.DataFrame, manager_names: dict):
    """
    Returns (names, z, text) for a plotly heatmap: z is win% (0-100,
    NaN where no games played), text is 'W-L' strings for cell labels.
    """
    import numpy as np

    owner_ids = sorted(
        set(weekly_history["owner_id"].dropna()) | set(weekly_history["opp_owner_id"].dropna()),
        key=lambda oid: manager_names.get(oid, "Unknown"),
    )
    names = [manager_names.get(oid, "Unknown") for oid in owner_ids]
    n = len(owner_ids)
    z = np.full((n, n), np.nan)
    text = [["" for _ in range(n)] for _ in range(n)]

    for i, oid in enumerate(owner_ids):
        mine = weekly_history[weekly_history["owner_id"] == oid]
        for j, opp_oid in enumerate(owner_ids):
            if oid == opp_oid:
                continue
            vs = mine[mine["opp_owner_id"] == opp_oid]
            if vs.empty:
                continue
            wins = int((vs["result"] == "W").sum())
            gp = len(vs)
            z[i][j] = round(wins / gp * 100)
            text[i][j] = f"{wins}-{gp - wins}"
    return names, z, text


# ---------------------------------------------------------------------
# Drafted rookies this season (for the offseason-moves relevance filter)
# ---------------------------------------------------------------------
@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_drafted_player_ids(season: int) -> set:
    league_id = api.SEASON_LEAGUE_IDS.get(season)
    if not league_id:
        return set()
    try:
        drafts = api.get_drafts(league_id)
    except Exception:
        return set()
    ids = set()
    for d in drafts:
        try:
            picks = api.get_draft_picks(d["draft_id"])
        except Exception:
            continue
        for p in picks:
            pid = p.get("player_id")
            if pid:
                ids.add(pid)
    return ids


def build_manager_career(owner_id: str, season_range: tuple, season_history: pd.DataFrame, weekly_history: pd.DataFrame) -> dict:
    lo, hi = season_range
    career_df = season_history[
        (season_history["owner_id"] == owner_id) & (season_history["season"] >= lo) & (season_history["season"] <= hi)
    ].sort_values("season")

    weekly_slice = weekly_history[
        (weekly_history["season"] >= lo) & (weekly_history["season"] <= hi) & (~weekly_history["is_playoff"])
    ]
    manager_weekly = weekly_slice[weekly_slice["owner_id"] == owner_id]
    league_avg_ppg = weekly_slice["points"].mean() if not weekly_slice.empty else None
    manager_ppg = manager_weekly["points"].mean() if not manager_weekly.empty else None
    ppg_plus = round((manager_ppg / league_avg_ppg) * 100, 1) if league_avg_ppg and manager_ppg is not None else None

    all_play = compute_all_play_pct(weekly_slice)
    all_play_row = all_play[all_play["owner_id"] == owner_id]
    all_play_pct = round(all_play_row["all_play_win_pct"].iloc[0], 3) if not all_play_row.empty else None

    full_weekly_slice = weekly_history[(weekly_history["season"] >= lo) & (weekly_history["season"] <= hi)]
    playoff_games = full_weekly_slice[(full_weekly_slice["owner_id"] == owner_id) & (full_weekly_slice["is_playoff"])]

    total_games = int((career_df["W"] + career_df["L"] + career_df["T"]).sum()) if not career_df.empty else 0
    total_pf = round(career_df["PF"].sum(), 1) if not career_df.empty else 0.0
    games_weighted_ppg = round(total_pf / total_games, 1) if total_games else 0.0

    return {
        "career_df": career_df,
        "seasons_played": len(career_df),
        "total_wins": int(career_df["W"].sum()) if not career_df.empty else 0,
        "total_losses": int(career_df["L"].sum()) if not career_df.empty else 0,
        "total_points": total_pf,
        "avg_ppg": games_weighted_ppg,
        "avg_ppg_plus": ppg_plus,
        "avg_all_play_pct": all_play_pct,
        "playoff_apps": int(career_df["Made Playoffs"].sum()) if not career_df.empty else 0,
        "championships": int(career_df["Champion"].sum()) if not career_df.empty else 0,
        "championship_appearances": int((career_df["Champion"] | career_df["Runner-Up"]).sum()) if not career_df.empty else 0,
        "division_titles": int(career_df["Division Champion"].sum()) if not career_df.empty and "Division Champion" in career_df.columns else 0,
        "playoff_wins": int(playoff_games["result"].eq("W").sum()),
        "playoff_losses": int(playoff_games["result"].eq("L").sum()),
    }


@st.cache_data(ttl=60 * 30, show_spinner=False)
def build_strength_of_schedule(season_range: tuple) -> pd.DataFrame:
    weekly = build_full_weekly_history()
    lo, hi = season_range
    weekly = weekly[(weekly["season"] >= lo) & (weekly["season"] <= hi) & (~weekly["is_playoff"])]
    if weekly.empty:
        return pd.DataFrame()

    league_avg_ppg = weekly["points"].mean()
    all_play = compute_all_play_pct(weekly)

    rows = []
    for (rid, oid), grp in weekly.groupby(["roster_id", "owner_id"]):
        games = len(grp)
        wins = int((grp["result"] == "W").sum())
        losses = int((grp["result"] == "L").sum())
        own_ppg = grp["points"].mean()
        opp_ppg = grp["opp_points"].mean()
        team_name = grp["Team"].iloc[-1]
        ap_row = all_play[(all_play["roster_id"] == rid) & (all_play["owner_id"] == oid)]
        ap_pct = ap_row["all_play_win_pct"].iloc[0] if not ap_row.empty else 0
        expected_wins = ap_pct * games
        rows.append(
            {
                "Team": team_name, "roster_id": rid, "owner_id": oid, "Games": games,
                "PPG": round(own_ppg, 1), "Opp PPG": round(opp_ppg, 1), "Net Margin": round(own_ppg - opp_ppg, 1),
                "PPG+": round((own_ppg / league_avg_ppg) * 100, 1) if league_avg_ppg else 0,
                "W": wins, "L": losses, "Expected W": round(expected_wins, 1), "Luck (+/-)": round(wins - expected_wins, 1),
            }
        )
    return pd.DataFrame(rows).sort_values("Luck (+/-)", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------
# Draft results lookup (used both by Draft History and to resolve
# traded picks to an actual slot like "1.05" once that draft happens)
# ---------------------------------------------------------------------
ROOKIE_DRAFT_SEASONS = [s for s in api.ALL_SEASONS if s != min(api.ALL_SEASONS)]  # excludes the 2024 startup draft


@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_draft_results(season: int) -> pd.DataFrame:
    """One row per pick for a season's draft(s): round, pick_no, slot within round, roster_id, player_id."""
    league_id = api.SEASON_LEAGUE_IDS.get(season)
    if not league_id:
        return pd.DataFrame()
    try:
        drafts = api.get_drafts(league_id)
    except Exception:
        return pd.DataFrame()

    rows = []
    for d in drafts:
        draft_id = d.get("draft_id")
        try:
            picks = api.get_draft_picks(draft_id)
        except Exception:
            continue
        for p in picks:
            rows.append(
                {
                    "season": season, "draft_id": draft_id,
                    "round": p.get("round"), "pick_no": p.get("pick_no"),
                    "roster_id": p.get("roster_id"), "player_id": p.get("player_id"),
                }
            )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["slot"] = df.groupby("round")["pick_no"].rank(method="first").astype(int)
    return df


def get_pick_label(season: int, round_: int, roster_id) -> str:
    """
    'R.SS' slot label (e.g. '1.05') for whoever ends up making that
    pick. Best-effort: matches on the CURRENT owner at the time this is
    called, so a pick that gets traded again after this lookup won't
    retroactively update here.
    """
    df = get_draft_results(season)
    if df.empty:
        return None
    match = df[(df["round"] == round_) & (df["roster_id"] == roster_id)]
    if match.empty:
        return None
    slot = int(match["slot"].iloc[0])
    return f"{round_}.{slot:02d}"


def _ordinal_round(round_: int) -> str:
    suffix = {1: "1st", 2: "2nd", 3: "3rd"}.get(round_, f"{round_}th")
    return suffix


# ---------------------------------------------------------------------
# Transactions log
# ---------------------------------------------------------------------
@st.cache_data(ttl=60 * 30, show_spinner=False)
def build_transactions_log(seasons: tuple) -> pd.DataFrame:
    all_players = api.get_all_players()
    rows = []
    for season in seasons:
        league_id = api.SEASON_LEAGUE_IDS.get(season)
        if not league_id:
            continue
        try:
            rosters = api.get_rosters(league_id)
            users = api.get_users(league_id)
        except Exception:
            continue
        owner_map = api.build_owner_map(users, rosters)
        owner_id_map = api.build_owner_id_map(users, rosters)

        seen_tx = set()
        for wk in range(0, 19):
            try:
                txs = api.get_transactions(league_id, wk)
            except Exception:
                continue
            for tx in txs:
                tx_id = tx.get("transaction_id")
                if tx_id in seen_tx:
                    continue
                seen_tx.add(tx_id)
                status = tx.get("status", "unknown")
                if status not in ("complete", "failed"):
                    continue

                adds = tx.get("adds") or {}
                drops = tx.get("drops") or {}
                tx_type = tx.get("type", "unknown")
                ts = tx.get("status_updated")
                date_str = pd.to_datetime(ts, unit="ms").strftime("%Y-%m-%d %I:%M %p") if ts else ""
                faab = (tx.get("settings") or {}).get("waiver_bid")

                # failed waiver claims: the players/roster involved live in
                # the "adds" dict even though nothing actually moved
                if status == "failed":
                    rosters_involved = set(list(adds.values()) + list(drops.values()))
                    for rid in rosters_involved:
                        my_adds = [pid for pid, r in adds.items() if r == rid]
                        add_names = ", ".join(all_players.get(p, {}).get("full_name", p) for p in my_adds)
                        rows.append(
                            {
                                "Season": season, "Week": wk, "Date": date_str, "Status": "Failed",
                                "Type": tx_type.replace("_", " ").title(),
                                "Team": owner_map.get(rid, "Unknown"), "With": owner_map.get(rid, "Unknown"),
                                "owner_id": owner_id_map.get(rid), "with_owner_id": None,
                                "FAAB": faab, "Summary": f"Failed bid: {add_names}" if add_names else "Failed bid",
                            }
                        )
                    continue

                draft_picks = tx.get("draft_picks") or []
                rosters_involved = set(list(adds.values()) + list(drops.values()))
                for pk in draft_picks:
                    if pk.get("owner_id") is not None:
                        rosters_involved.add(pk["owner_id"])
                    if pk.get("previous_owner_id") is not None:
                        rosters_involved.add(pk["previous_owner_id"])

                for rid in rosters_involved:
                    my_adds = [pid for pid, r in adds.items() if r == rid]
                    my_drops = [pid for pid, r in drops.items() if r == rid]
                    add_names_list = [all_players.get(p, {}).get("full_name", p) for p in my_adds]
                    drop_names_list = [all_players.get(p, {}).get("full_name", p) for p in my_drops]

                    with_team = None
                    with_owner_id = None
                    if tx_type == "trade" and len(rosters_involved) > 1:
                        other = [r for r in rosters_involved if r != rid]
                        if other:
                            with_team = owner_map.get(other[0])
                            with_owner_id = owner_id_map.get(other[0])

                    if tx_type == "trade":
                        for pk in draft_picks:
                            pk_season, pk_round, pk_orig_roster = pk.get("season"), pk.get("round"), pk.get("roster_id")
                            if not pk_season or not pk_round:
                                continue
                            slot_label = get_pick_label(int(pk_season), int(pk_round), pk_orig_roster)
                            label = f"{pk_season} {_ordinal_round(pk_round)} Round Pick"
                            if slot_label:
                                label += f" ({slot_label})"
                            if pk.get("owner_id") == rid:
                                add_names_list.append(label)
                            elif pk.get("previous_owner_id") == rid:
                                drop_names_list.append(label)

                    add_names = ", ".join(add_names_list)
                    drop_names = ", ".join(drop_names_list)

                    summary_parts = []
                    if tx_type == "trade":
                        # Received = what this manager got, Sent = what they
                        # gave up - not "Added/Dropped", which reads backwards
                        # for a trade
                        if add_names:
                            summary_parts.append(f"Received: {add_names}")
                        if drop_names:
                            summary_parts.append(f"Sent: {drop_names}")
                    else:
                        if add_names:
                            summary_parts.append(f"Added: {add_names}")
                        if drop_names:
                            summary_parts.append(f"Dropped: {drop_names}")

                    rows.append(
                        {
                            "Season": season, "Week": wk, "Date": date_str, "Status": "Complete",
                            "Type": tx_type.replace("_", " ").title(),
                            "Team": owner_map.get(rid, "Unknown"),
                            "With": with_team or owner_map.get(rid, "Unknown"),
                            "owner_id": owner_id_map.get(rid), "with_owner_id": with_owner_id,
                            "FAAB": faab if tx_type == "waiver" else None,
                            "Summary": " | ".join(summary_parts) if summary_parts else "-",
                        }
                    )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Date", ascending=False).reset_index(drop=True)
    return df


@st.cache_data(ttl=60 * 30, show_spinner=False)
def build_draft_history(season: int) -> pd.DataFrame:
    """Full rookie draft board for a season: Round, Pick (slot), Team, Player, Pos, NFL Team."""
    all_players = api.get_all_players()
    df = get_draft_results(season)
    if df.empty:
        return pd.DataFrame()

    league_id = api.SEASON_LEAGUE_IDS.get(season)
    try:
        rosters = api.get_rosters(league_id)
        users = api.get_users(league_id)
        owner_map = api.build_owner_map(users, rosters)
    except Exception:
        owner_map = {}

    rows = []
    for _, r in df.sort_values("pick_no").iterrows():
        p = all_players.get(r["player_id"], {})
        rows.append(
            {
                "Round": int(r["round"]), "Pick": f"{int(r['round'])}.{int(r['slot']):02d}",
                "Overall": int(r["pick_no"]),
                "Team": owner_map.get(r["roster_id"], "Unknown"),
                "Player": p.get("full_name", r["player_id"]),
                "Pos": p.get("position", "-"), "NFL Team": p.get("team") or "FA",
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------
# UDFA signings - rookies who were NOT drafted in that season's rookie
# draft but got picked up off waivers/free agency before the season
# really got going (e.g. Jalen Milroe, RJ Fannin-type pickups). Rookie
# status is inferred from Sleeper's current years_exp field: a player
# with years_exp == N was a rookie (years_exp == 0) N seasons ago, so
# rookie_season ≈ CURRENT_SEASON - years_exp. This is an approximation
# since Sleeper doesn't expose historical snapshots, but it's accurate
# for any season within the last few years, which is all we track.
# ---------------------------------------------------------------------
POSITIONS_TRACKED = {"QB", "RB", "WR", "TE", "K", "DEF"}

import datetime


def _season_kickoff_date(season: int) -> datetime.date:
    """First Thursday of September that season - real NFL kickoff, used
    as the actual cutoff for 'before the season started' instead of
    trusting Sleeper's transaction round number (which doesn't reliably
    line up with calendar week during the offseason)."""
    d = datetime.date(season, 9, 1)
    days_ahead = (3 - d.weekday()) % 7  # Thursday == weekday 3
    return d + datetime.timedelta(days=days_ahead)


@st.cache_data(ttl=60 * 30, show_spinner=False)
def build_udfa_signings(season: int) -> pd.DataFrame:
    """Season, Team, Player, Pos, NFL Team - rookies added via waiver/FA before kickoff, not drafted that season."""
    league_id = api.SEASON_LEAGUE_IDS.get(season)
    if not league_id:
        return pd.DataFrame()

    all_players = api.get_all_players()
    try:
        rosters = api.get_rosters(league_id)
        users = api.get_users(league_id)
        owner_map = api.build_owner_map(users, rosters)
    except Exception:
        return pd.DataFrame()

    draft_df = get_draft_results(season)
    drafted_ids = set(draft_df["player_id"]) if not draft_df.empty else set()
    target_years_exp = api.CURRENT_SEASON - season
    kickoff = pd.Timestamp(_season_kickoff_date(season))

    seen = set()  # (roster_id, player_id)
    for wk in range(0, 3):  # scan generously, real filtering is by date below
        try:
            txs = api.get_transactions(league_id, wk)
        except Exception:
            continue
        for tx in txs:
            if tx.get("status") != "complete" or tx.get("type") not in ("waiver", "free_agent"):
                continue
            ts = tx.get("status_updated")
            if ts is None or pd.to_datetime(ts, unit="ms") >= kickoff:
                continue  # happened on/after kickoff - not a preseason UDFA pickup
            adds = tx.get("adds") or {}
            for pid, rid in adds.items():
                if pid in drafted_ids:
                    continue
                p = all_players.get(pid, {})
                if p.get("position") not in POSITIONS_TRACKED:
                    continue
                if p.get("years_exp") != target_years_exp:
                    continue
                seen.add((rid, pid))

    rows = []
    for (rid, pid) in seen:
        p = all_players.get(pid, {})
        rows.append(
            {
                "Season": season, "Team": owner_map.get(rid, "Unknown"),
                "Player": p.get("full_name", pid), "Pos": p.get("position", "-"),
                "NFL Team": p.get("team") or "FA",
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Team", "Pos"]).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------
# Draft value analysis - steals & whiffs. Compares where a player was
# drafted (pick_no, lower = earlier/more capital spent) against their
# CURRENT dynasty trade value from FantasyCalc. A player who went late
# but now has high value is a steal; a player who went early but has
# low value now is a whiff. This is inherently a snapshot-in-time read
# (values move), not a final verdict.
# ---------------------------------------------------------------------
STEAL_WHIFF_THRESHOLD = 8  # rank-delta needed to earn the tag


@st.cache_data(ttl=60 * 30, show_spinner=False)
def build_draft_value_analysis(season: int) -> pd.DataFrame:
    all_players = api.get_all_players()
    df = get_draft_results(season)
    if df.empty:
        return pd.DataFrame()

    league_id = api.SEASON_LEAGUE_IDS.get(season)
    try:
        rosters = api.get_rosters(league_id)
        users = api.get_users(league_id)
        owner_map = api.build_owner_map(users, rosters)
    except Exception:
        owner_map = {}

    values = get_fantasycalc_values()
    if not values:
        return pd.DataFrame()

    rows = []
    for _, r in df.iterrows():
        pid = r["player_id"]
        p = all_players.get(pid, {})
        v = values.get(str(pid))
        rows.append(
            {
                "Pick": f"{int(r['round'])}.{int(r['slot']):02d}", "Overall": int(r["pick_no"]),
                "Team": owner_map.get(r["roster_id"], "Unknown"),
                "Player": p.get("full_name", pid), "Pos": p.get("position", "-"),
                "Current Value": v["value"] if v else 0,
            }
        )
    out = pd.DataFrame(rows)
    out["Draft Rank"] = out["Overall"].rank(method="first").astype(int)
    out["Value Rank"] = out["Current Value"].rank(method="first", ascending=False).astype(int)
    out["Delta"] = out["Draft Rank"] - out["Value Rank"]
    out["Tag"] = out["Delta"].apply(
        lambda d: "🔥 Steal" if d >= STEAL_WHIFF_THRESHOLD else ("❄️ Whiff" if d <= -STEAL_WHIFF_THRESHOLD else "")
    )
    return out.sort_values("Overall").reset_index(drop=True)


def build_trade_counts(txn_df: pd.DataFrame, owner_id: str) -> pd.DataFrame:
    """
    Per-counterparty trade summary for one manager: total trades, most
    recent season, and a running summary of what was received/sent
    each time. Matches Bozos' "Trade counts for X" view.
    """
    trades = txn_df[(txn_df["Type"] == "Trade") & (txn_df["owner_id"] == owner_id) & (txn_df["Status"] == "Complete")]
    if trades.empty:
        return pd.DataFrame()

    rows = []
    for with_owner_id, grp in trades.groupby("with_owner_id"):
        if with_owner_id is None:
            continue
        grp_sorted = grp.sort_values("Season")
        numbered = [f"{i}. {summary}" for i, summary in enumerate(grp_sorted["Summary"], start=1)]
        rows.append(
            {
                "Counterparty": grp_sorted["With"].iloc[-1],
                "Trades": len(grp_sorted),
                "Most Recent Season": int(grp_sorted["Season"].max()),
                "Summary": "   ".join(numbered),
            }
        )
    return pd.DataFrame(rows).sort_values("Trades", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------
# Offseason roster diff (Player Profile) - fixed version. Compares
# actual roster membership between the current season and the prior
# season's FINAL roster, matched by owner_id. This avoids the earlier
# bug where a player added then dropped in the same offseason (or a
# player who was never actually on last year's roster) showed up as
# both an add and a removal - now it's a pure set difference of two
# real rosters, so a net-zero move nets to nothing and "removed" only
# ever means "was actually on the roster last year, isn't now."
#
# Relevance filter: a rookie drafted in this season's draft always
# counts (a rookie pick is inherently notable even before he's scored
# a point), but any other add/drop only counts if the player clears a
# fantasy-relevance bar (Sleeper's search_rank, lower = more relevant)
# so waiver-wire scrubs like a QB3 stashed for a bye week don't clutter
# the list.
# ---------------------------------------------------------------------
RELEVANCE_SEARCH_RANK = 200


@st.cache_data(ttl=60 * 30, show_spinner=False)
def build_roster_diff(current_season: int, previous_season: int) -> dict:
    all_players = api.get_all_players()
    POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}
    drafted_ids = get_drafted_player_ids(current_season)

    cur_lid = api.SEASON_LEAGUE_IDS.get(current_season)
    prev_lid = api.SEASON_LEAGUE_IDS.get(previous_season)
    if not cur_lid or not prev_lid:
        return {}

    try:
        cur_rosters = api.get_rosters(cur_lid)
        prev_rosters = api.get_rosters(prev_lid)
    except Exception:
        return {}

    cur_owner_players = {r.get("owner_id"): set(r.get("players") or []) for r in cur_rosters}
    prev_owner_players = {r.get("owner_id"): set(r.get("players") or []) for r in prev_rosters}

    def _relevant_add(pid):
        p = all_players.get(pid, {})
        if p.get("position") not in POSITIONS:
            return False
        if pid in drafted_ids:
            return True  # drafted rookie - always relevant regardless of early search_rank
        return (p.get("search_rank") or 9999) <= RELEVANCE_SEARCH_RANK

    def _relevant_drop(pid):
        p = all_players.get(pid, {})
        if p.get("position") not in POSITIONS:
            return False
        return (p.get("search_rank") or 9999) <= RELEVANCE_SEARCH_RANK

    diff = {}
    for owner_id, cur_players in cur_owner_players.items():
        prev_players = prev_owner_players.get(owner_id, set())
        added_ids = cur_players - prev_players
        removed_ids = prev_players - cur_players

        added = sorted(
            (pid for pid in added_ids if _relevant_add(pid)),
            key=lambda pid: 0 if pid in drafted_ids else (all_players.get(pid, {}).get("search_rank") or 9999),
        )[:5]
        removed = sorted(
            (pid for pid in removed_ids if _relevant_drop(pid)),
            key=lambda pid: all_players.get(pid, {}).get("search_rank") or 9999,
        )[:5]

        diff[owner_id] = {
            "added": [
                {
                    "name": all_players.get(pid, {}).get("full_name", pid),
                    "pos": all_players.get(pid, {}).get("position"),
                    "team": all_players.get(pid, {}).get("team") or "FA",
                    "rookie": pid in drafted_ids,
                }
                for pid in added
            ],
            "removed": [
                {"name": all_players.get(pid, {}).get("full_name", pid), "pos": all_players.get(pid, {}).get("position"), "team": all_players.get(pid, {}).get("team") or "FA"}
                for pid in removed
            ],
        }
    return diff


# ---------------------------------------------------------------------
# Dynasty Value (Player Profile) - pulls live trade values from
# FantasyCalc's public API (external to Sleeper) and breaks a roster
# down by position and value tier. NOTE: this hits a third-party API
# I could not reach or test from this sandbox (only Sleeper's domain
# is reachable here), so the field names below are my best
# understanding of FantasyCalc's response shape, not a verified
# integration. If this comes back empty or errors, that's the first
# thing to check.
# ---------------------------------------------------------------------
FANTASYCALC_URL = "https://api.fantasycalc.com/values/current"


@st.cache_data(ttl=60 * 60, show_spinner=False)
def get_fantasycalc_values(num_teams: int = 12, ppr: float = 1, num_qbs: int = 1) -> dict:
    """Dynasty trade values keyed by Sleeper player_id (string)."""
    import requests

    try:
        resp = requests.get(
            FANTASYCALC_URL,
            params={"isDynasty": "true", "numQbs": num_qbs, "numTeams": num_teams, "ppr": ppr},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return {}

    values = {}
    for entry in data:
        player = entry.get("player", {}) or {}
        sleeper_id = player.get("sleeperId")
        if not sleeper_id:
            continue
        # FantasyCalc's 30-day trend field name isn't something I could
        # verify live - trying the couple of variants I've seen documented
        trend = entry.get("trend30Day", entry.get("trend_30_day", 0)) or 0
        values[str(sleeper_id)] = {
            "value": entry.get("value", 0) or 0,
            "position": player.get("position", "UNK"),
            "name": player.get("name", "Unknown"),
            "trend_30day": trend,
        }
    return values


def _dynasty_tier_for(value: float) -> str:
    if value >= 6000:
        return "Elite"
    if value >= 3500:
        return "Core"
    if value >= 1500:
        return "Flex"
    if value >= 500:
        return "Depth"
    return "Lottery"


def build_dynasty_value_breakdown(roster_player_ids: list, all_players: dict) -> dict:
    """
    Dynasty Value by Position for one roster: total value, per-position
    share, and a tier breakdown (Elite/Core/Flex/Depth/Lottery) by
    value bucket. Draft picks aren't included yet (that needs the
    traded_picks endpoint plus matching FantasyCalc's pick valuations -
    next pass), so this is player value only for now.
    """
    values = get_fantasycalc_values()
    if not values:
        return {}

    assets = []
    for pid in roster_player_ids or []:
        v = values.get(str(pid))
        if not v or v["value"] <= 0:
            continue
        p = all_players.get(pid, {})
        assets.append(
            {
                "player_id": pid,
                "name": p.get("full_name", v["name"]),
                "position": p.get("position", v["position"]),
                "value": v["value"],
            }
        )
    if not assets:
        return {}

    total_value = sum(a["value"] for a in assets)
    by_position = {}
    for a in assets:
        by_position.setdefault(a["position"], 0)
        by_position[a["position"]] += a["value"]

    position_rows = sorted(
        [{"position": pos, "value": val, "share": round(val / total_value * 100)} for pos, val in by_position.items()],
        key=lambda r: r["value"], reverse=True,
    )

    tiers = {"Elite": [], "Core": [], "Flex": [], "Depth": [], "Lottery": []}
    for a in sorted(assets, key=lambda x: x["value"], reverse=True):
        tiers[_dynasty_tier_for(a["value"])].append(a)

    tier_rows = []
    for tier_name in ["Elite", "Core", "Flex", "Depth", "Lottery"]:
        tier_assets = tiers[tier_name]
        tier_value = sum(a["value"] for a in tier_assets)
        tier_rows.append(
            {
                "tier": tier_name, "count": len(tier_assets),
                "share": round(tier_value / total_value * 100) if total_value else 0,
                "top_assets": tier_assets,
            }
        )

    return {"total_value": total_value, "position_rows": position_rows, "tier_rows": tier_rows}


# ---------------------------------------------------------------------
# League-wide position value ranks (e.g. "QB: 2/10") + biggest
# risers/droppers on a roster over the last 30 days, per FantasyCalc.
# ---------------------------------------------------------------------
@st.cache_data(ttl=60 * 30, show_spinner=False)
def build_league_dynasty_value_table() -> pd.DataFrame:
    """One row per current-season roster with total dynasty value by position - used to rank a team's QB/RB/WR/TE value against the rest of the league."""
    league_id = api.CURRENT_LEAGUE_ID
    try:
        rosters = api.get_rosters(league_id)
        users = api.get_users(league_id)
    except Exception:
        return pd.DataFrame()
    owner_map = api.build_owner_map(users, rosters)
    all_players = api.get_all_players()
    values = get_fantasycalc_values()
    if not values:
        return pd.DataFrame()

    rows = []
    for r in rosters:
        pos_totals = {"QB": 0, "RB": 0, "WR": 0, "TE": 0}
        for pid in r.get("players") or []:
            v = values.get(str(pid))
            if not v:
                continue
            p = all_players.get(pid, {})
            pos = p.get("position", v["position"])
            if pos in pos_totals:
                pos_totals[pos] += v["value"]
        rows.append({"roster_id": r["roster_id"], "owner_id": r.get("owner_id"), "Team": owner_map.get(r["roster_id"], "Unknown"), **pos_totals})
    return pd.DataFrame(rows)


def get_position_rank(league_dv_df: pd.DataFrame, owner_id: str, position: str):
    """Returns (rank, total_teams) for this owner's total value at a position, or None."""
    if league_dv_df.empty or position not in league_dv_df.columns:
        return None
    ranked = league_dv_df.sort_values(position, ascending=False).reset_index(drop=True)
    match = ranked[ranked["owner_id"] == owner_id]
    if match.empty:
        return None
    return (int(match.index[0]) + 1, len(ranked))


def build_value_movers(roster_player_ids: list, all_players: dict, n: int = 3) -> dict:
    """Biggest risers/droppers on a roster over the last 30 days, per FantasyCalc's trend field."""
    values = get_fantasycalc_values()
    if not values:
        return {"risers": [], "droppers": []}

    assets = []
    for pid in roster_player_ids or []:
        v = values.get(str(pid))
        if not v:
            continue
        p = all_players.get(pid, {})
        assets.append(
            {
                "player_id": pid, "name": p.get("full_name", v["name"]),
                "position": p.get("position", v["position"]), "value": v["value"],
                "trend_30day": v.get("trend_30day", 0),
            }
        )
    movers = [a for a in assets if a["trend_30day"] != 0]
    risers = sorted(movers, key=lambda a: a["trend_30day"], reverse=True)[:n]
    droppers = sorted(movers, key=lambda a: a["trend_30day"])[:n]
    return {"risers": risers, "droppers": droppers}

def build_failed_bids(seasons: tuple) -> pd.DataFrame:
    """Waiver bids that lost to a higher bid, with the closest completed add for that player afterward (if any)."""
    all_players = api.get_all_players()
    failed_rows = []
    completed_adds = []

    for season in seasons:
        league_id = api.SEASON_LEAGUE_IDS.get(season)
        if not league_id:
            continue
        try:
            rosters = api.get_rosters(league_id)
            users = api.get_users(league_id)
        except Exception:
            continue
        owner_map = api.build_owner_map(users, rosters)

        seen_tx = set()
        for wk in range(0, 19):
            try:
                txs = api.get_transactions(league_id, wk)
            except Exception:
                continue
            for tx in txs:
                tx_id = tx.get("transaction_id")
                if tx_id in seen_tx:
                    continue
                seen_tx.add(tx_id)
                status = tx.get("status", "unknown")
                tx_type = tx.get("type", "unknown")
                if status not in ("complete", "failed"):
                    continue
                if tx_type not in ("waiver", "free_agent"):
                    continue

                adds = tx.get("adds") or {}
                ts = tx.get("status_updated")
                dt = pd.to_datetime(ts, unit="ms") if ts else None
                faab = (tx.get("settings") or {}).get("waiver_bid")

                if status == "failed":
                    for pid, rid in adds.items():
                        failed_rows.append({
                            "Season": season, "Week": wk, "Date": dt,
                            "Team": owner_map.get(rid, "Unknown"),
                            "player_id": pid,
                            "Player": all_players.get(pid, {}).get("full_name", pid),
                            "FAAB": faab,
                        })
                else:
                    for pid, rid in adds.items():
                        completed_adds.append({
                            "season": season, "date": dt,
                            "team": owner_map.get(rid, "Unknown"),
                            "player_id": pid,
                        })

    rows = []
    for fb in failed_rows:
        went_to = None
        best_dt = None
        for ca in completed_adds:
            if ca["season"] != fb["Season"] or ca["player_id"] != fb["player_id"]:
                continue
            if fb["Date"] is not None and ca["date"] is not None and ca["date"] < fb["Date"]:
                continue
            if best_dt is None or (ca["date"] is not None and ca["date"] < best_dt):
                best_dt = ca["date"]
                went_to = ca["team"]
        if went_to is None:
            continue
        rows.append({
            "Season": fb["Season"], "Week": fb["Week"],
            "Date": fb["Date"].strftime("%Y-%m-%d %I:%M %p") if fb["Date"] is not None else "",
            "Team": fb["Team"], "Player": fb["Player"], "FAAB": fb["FAAB"],
            "Went To": went_to,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Date", ascending=False).reset_index(drop=True)
    return df

# ---------------------------------------------------------------------
# FAAB spend stats
# ---------------------------------------------------------------------
def build_faab_stats(txn_df):
    waivers = txn_df[(txn_df["Type"] == "Waiver") & (txn_df["Status"] == "Complete") & (txn_df["FAAB"].notna())]
    if waivers.empty:
        return {}
    biggest = waivers.sort_values("FAAB", ascending=False).iloc[0]
    by_season = waivers.groupby("Season")["FAAB"].agg(["sum", "mean", "count"]).reset_index().rename(
        columns={"sum": "Total FAAB", "mean": "Avg FAAB", "count": "Waivers Won"}
    )
    by_season["Avg FAAB"] = by_season["Avg FAAB"].round(1)
    by_team = waivers.groupby("Team")["FAAB"].agg(["sum", "mean", "count"]).reset_index().rename(
        columns={"sum": "Total FAAB", "mean": "Avg FAAB", "count": "Waivers Won"}
    )
    by_team["Avg FAAB"] = by_team["Avg FAAB"].round(1)
    by_team = by_team.sort_values("Total FAAB", ascending=False).reset_index(drop=True)
    return {
        "avg_faab": round(waivers["FAAB"].mean(), 1),
        "biggest_bid": biggest,
        "by_season": by_season.sort_values("Season").reset_index(drop=True),
        "by_team": by_team,
    }


# ---------------------------------------------------------------------
# Best waiver wire adds
# ---------------------------------------------------------------------
@st.cache_data(ttl=60 * 30, show_spinner=False)
def build_waiver_adds_detail(seasons):
    all_players = api.get_all_players()
    rows = []
    for season in seasons:
        league_id = api.SEASON_LEAGUE_IDS.get(season)
        if not league_id:
            continue
        try:
            rosters = api.get_rosters(league_id)
            users = api.get_users(league_id)
            owner_map = api.build_owner_map(users, rosters)
            owner_id_map = api.build_owner_id_map(users, rosters)
        except Exception:
            continue
        seen_tx = set()
        for wk in range(0, 19):
            try:
                txs = api.get_transactions(league_id, wk)
            except Exception:
                continue
            for tx in txs:
                tid = tx.get("transaction_id")
                if tid in seen_tx:
                    continue
                seen_tx.add(tid)
                if tx.get("status") != "complete" or tx.get("type") not in ("waiver", "free_agent"):
                    continue
                faab = (tx.get("settings") or {}).get("waiver_bid")
                ts = tx.get("status_updated")
                for pid, rid in (tx.get("adds") or {}).items():
                    p = all_players.get(pid, {})
                    rows.append(
                        {
                            "season": season, "player_id": pid, "roster_id": rid,
                            "owner_id": owner_id_map.get(rid), "Team": owner_map.get(rid, "Unknown"),
                            "Player": p.get("full_name", pid), "Pos": p.get("position", "-"),
                            "FAAB": faab if faab is not None else 0,
                            "Date": pd.to_datetime(ts, unit="ms").strftime("%Y-%m-%d") if ts else "",
                        }
                    )
    return pd.DataFrame(rows)


def build_best_waiver_adds(waiver_detail_df, owner_id=None, n=10):
    values = get_fantasycalc_values()
    if waiver_detail_df.empty or not values:
        return pd.DataFrame()
    df = waiver_detail_df if owner_id is None else waiver_detail_df[waiver_detail_df["owner_id"] == owner_id]
    df = df.sort_values("Date").drop_duplicates(subset=["player_id"], keep="last")
    rows = []
    for _, r in df.iterrows():
        v = values.get(str(r["player_id"]))
        cur_val = v["value"] if v else 0
        if cur_val <= 0:
            continue
        rows.append(
            {"Season": r["season"], "Team": r["Team"], "Player": r["Player"], "Pos": r["Pos"], "FAAB Spent": r["FAAB"], "Current Value": cur_val}
        )
    return pd.DataFrame(rows).sort_values("Current Value", ascending=False).head(n).reset_index(drop=True)


# ---------------------------------------------------------------------
# Local dynasty-value snapshots
# ---------------------------------------------------------------------
import json
import os

SNAPSHOT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dynasty_value_snapshots.json")


def _load_snapshots():
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def snapshot_dynasty_values_if_needed():
    today = datetime.date.today().isoformat()
    snapshots = _load_snapshots()
    if today in snapshots:
        return
    values = get_fantasycalc_values()
    if not values:
        return
    snapshots[today] = {pid: v["value"] for pid, v in values.items()}
    if len(snapshots) > 400:
        for old_date in sorted(snapshots.keys())[: len(snapshots) - 400]:
            del snapshots[old_date]
    try:
        with open(SNAPSHOT_FILE, "w") as f:
            json.dump(snapshots, f)
    except Exception:
        pass


def get_earliest_snapshot_date():
    snapshots = _load_snapshots()
    return min(snapshots.keys()) if snapshots else None


def build_value_movers_v2(roster_player_ids, all_players, n=4, min_change=50):
    """Biggest risers/droppers on a roster over the last 30 days (FantasyCalc trend) - only moves big enough to matter."""
    values = get_fantasycalc_values()
    if not values:
        return {"risers": [], "droppers": [], "note": "No FantasyCalc data available."}

    assets = []
    for pid in roster_player_ids or []:
        v = values.get(str(pid))
        if not v:
            continue
        p = all_players.get(pid, {})
        assets.append({
            "player_id": pid, "name": p.get("full_name", v["name"]),
            "position": p.get("position", v["position"]), "value": v["value"],
            "change": v.get("trend_30day", 0),
        })
    movers = [a for a in assets if abs(a["change"]) >= min_change]
    note = None if movers else "No significant 30-day value moves on this roster right now."

    risers = sorted([a for a in movers if a["change"] > 0], key=lambda a: a["change"], reverse=True)[:n]
    droppers = sorted([a for a in movers if a["change"] < 0], key=lambda a: a["change"])[:n]
    return {"risers": risers, "droppers": droppers, "note": note}


# ---------------------------------------------------------------------
# Trade grades - hindsight value comparison using current FantasyCalc
# values. Resolved picks are valued as the actual player drafted with
# them; unresolved future picks use a standard round/slot/years-out
# estimate chart (NOT FantasyCalc data - they don't expose pick values
# via the public API, so this is a best-effort industry-standard chart).
# ---------------------------------------------------------------------
PICK_ROUND_BASE = {1: 4000, 2: 1200, 3: 500, 4: 250}


def estimate_pick_value(pk_season, pk_round: int, current_season: int) -> int:
    base = PICK_ROUND_BASE.get(pk_round, 100)
    years_out = max(0, int(pk_season) - current_season)
    return round(base * (0.90 ** years_out))


@functools.lru_cache(maxsize=32)
def _get_owner_id_to_roster_id(season: int) -> dict:
    """owner_id -> roster_id for a given season's league - lets us translate a roster_id
    from one season's numbering into another season's numbering for the same manager."""
    league_id = api.SEASON_LEAGUE_IDS.get(season)
    if not league_id:
        return {}
    try:
        rosters = api.get_rosters(league_id)
        users = api.get_users(league_id)
        owner_id_map = api.build_owner_id_map(users, rosters)  # roster_id -> owner_id
    except Exception:
        return {}
    return {v: k for k, v in owner_id_map.items()}  # flip to owner_id -> roster_id


@functools.lru_cache(maxsize=1)
def build_pick_ownership_log() -> dict:
    """(pick_season_str, round, origin_persistent_owner_id) -> final_persistent_owner_id.
    Self-derived by scanning every trade across every season's league, tracking every
    reassignment of a given pick and keeping whichever happened most recently. This avoids
    depending on Sleeper's traded_picks endpoint, which appears to drop entries once a
    pick's season has already been drafted - exactly the case that was failing."""
    log = {}  # key -> (latest_timestamp, final_owner_id)
    for season, league_id in api.SEASON_LEAGUE_IDS.items():
        try:
            rosters = api.get_rosters(league_id)
            users = api.get_users(league_id)
            owner_id_map = api.build_owner_id_map(users, rosters)  # this season's roster_id -> persistent owner_id
        except Exception:
            continue

        seen_tx = set()
        for wk in range(0, 19):
            try:
                txs = api.get_transactions(league_id, wk)
            except Exception:
                continue
            for tx in txs:
                tx_id = tx.get("transaction_id")
                if tx_id in seen_tx or tx.get("status") != "complete" or tx.get("type") != "trade":
                    continue
                seen_tx.add(tx_id)
                ts = tx.get("status_updated") or 0
                for pk in (tx.get("draft_picks") or []):
                    origin_owner = owner_id_map.get(pk.get("roster_id"))
                    new_owner = owner_id_map.get(pk.get("owner_id"))
                    if origin_owner is None or new_owner is None:
                        continue
                    try:
                        key = (str(pk.get("season")), int(pk.get("round")), origin_owner)
                    except (TypeError, ValueError):
                        continue
                    prev = log.get(key)
                    if prev is None or ts > prev[0]:
                        log[key] = (ts, new_owner)
    return {k: v[1] for k, v in log.items()}


def _resolve_pick_value(pk_season, pk_round, pk_orig_roster, current_season: int, values: dict,
                         all_players: dict, trade_owner_id_map: dict) -> tuple:
    """Returns (value, label, is_estimate). Follows the pick through however many re-trades
    it went through (via our own reconstructed ownership log) before matching it to who
    actually drafted with it."""
    pk_season = int(pk_season)
    pk_round = int(pk_round)

    origin_owner_id = trade_owner_id_map.get(pk_orig_roster)
    final_roster_id_draft_season = None

    if origin_owner_id is not None:
        ownership_log = build_pick_ownership_log()
        final_owner_id = ownership_log.get((str(pk_season), pk_round, origin_owner_id), origin_owner_id)
        final_roster_id_draft_season = _get_owner_id_to_roster_id(pk_season).get(final_owner_id)

    df = get_draft_results(pk_season)
    if not df.empty and final_roster_id_draft_season is not None:
        match = df[(df["round"] == pk_round) & (df["roster_id"] == final_roster_id_draft_season)]
        if not match.empty:
            row = match.iloc[0]
            pid = str(row.get("player_id", ""))
            v = values.get(pid)
            player_name = all_players.get(pid, {}).get("full_name", pid)
            label = f"{pk_season} {_ordinal_round(pk_round)} ({player_name})"
            return (v["value"] if v else 0), label, False

    slot_label = get_pick_label(
        pk_season, pk_round,
        final_roster_id_draft_season if final_roster_id_draft_season is not None else pk_orig_roster
    )
    label = f"{pk_season} {_ordinal_round(pk_round)} Round Pick" + (f" ({slot_label})" if slot_label else "")
    return estimate_pick_value(pk_season, pk_round, current_season), label, True


TRADE_GRADE_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_grade_log.json")


def _load_trade_grade_log() -> dict:
    if os.path.exists(TRADE_GRADE_LOG_FILE):
        try:
            with open(TRADE_GRADE_LOG_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_trade_grade_log(log: dict) -> None:
    try:
        with open(TRADE_GRADE_LOG_FILE, "w") as f:
            json.dump(log, f)
    except Exception:
        pass


CONSOLIDATION_WEIGHTS = [1.0, 0.85, 0.70, 0.55, 0.40]


def weighted_package_value(values_list: list) -> int:
    """Diminishing-returns discount for multi-asset packages - one elite asset should
    outweigh several lesser ones of equal raw total, since roster spots are scarce and
    spreading value across more players carries more bust risk than one proven piece."""
    ranked = sorted(values_list, reverse=True)
    total = 0.0
    for i, v in enumerate(ranked):
        weight = CONSOLIDATION_WEIGHTS[i] if i < len(CONSOLIDATION_WEIGHTS) else CONSOLIDATION_WEIGHTS[-1]
        total += v * weight
    return round(total)


def build_trade_grades(seasons: tuple, current_season: int) -> pd.DataFrame:
    all_players = api.get_all_players()
    values = get_fantasycalc_values()
    rows = []
    grade_log = _load_trade_grade_log()
    log_dirty = False
    today_str = datetime.date.today().isoformat()

    for season in seasons:
        league_id = api.SEASON_LEAGUE_IDS.get(season)
        if not league_id:
            continue
        try:
            rosters = api.get_rosters(league_id)
            users = api.get_users(league_id)
        except Exception:
            continue
        owner_map = api.build_owner_map(users, rosters)
        trade_owner_id_map = api.build_owner_id_map(users, rosters)  # this season's roster_id -> owner_id

        seen_tx = set()
        for wk in range(0, 19):
            try:
                txs = api.get_transactions(league_id, wk)
            except Exception:
                continue
            for tx in txs:
                tx_id = tx.get("transaction_id")
                if tx_id in seen_tx or tx.get("status") != "complete" or tx.get("type") != "trade":
                    continue
                seen_tx.add(tx_id)

                adds = tx.get("adds") or {}
                draft_picks = tx.get("draft_picks") or []
                ts = tx.get("status_updated")
                date_str = pd.to_datetime(ts, unit="ms").strftime("%Y-%m-%d") if ts else ""

                rosters_involved = set(adds.values())
                for pk in draft_picks:
                    if pk.get("owner_id") is not None:
                        rosters_involved.add(pk["owner_id"])
                if len(rosters_involved) != 2:
                    continue

                side_a, side_b = list(rosters_involved)
                side_data = {}
                for rid in (side_a, side_b):
                    asset_values = []
                    assets = []
                    for pid, r in adds.items():
                        if r != rid:
                            continue
                        v = values.get(str(pid))
                        p = all_players.get(pid, {})
                        val = v["value"] if v else 0
                        asset_values.append(val)
                        assets.append(f"{p.get('full_name', pid)} ({val:,})")
                    for pk in draft_picks:
                        if pk.get("owner_id") != rid:
                            continue
                        pk_val, pk_label, is_est = _resolve_pick_value(
                            pk.get("season"), pk.get("round"), pk.get("roster_id"), current_season, values, all_players, trade_owner_id_map
                        )
                        asset_values.append(pk_val)
                        assets.append(f"{pk_label} ({pk_val:,}{'*' if is_est else ''})")
                    total = weighted_package_value(asset_values)
                    side_data[rid] = {"team": owner_map.get(rid, "Unknown"), "value": total, "assets": ", ".join(assets)}

                val_a, val_b = side_data[side_a]["value"], side_data[side_b]["value"]
                if val_a == 0 and val_b == 0:
                    continue
                avg = max((val_a + val_b) / 2, 1)
                margin_a = (val_a - val_b) / avg * 100

                def grade_and_label(margin):
                    abs_m = abs(margin)
                    if abs_m < 22:
                        return "C", "Fair"
                    elif abs_m < 38:
                        return ("B", "Win") if margin > 0 else ("D", "Loss")
                    elif abs_m < 55:
                        return ("A-", "Win") if margin > 0 else ("D-", "Loss")
                    elif abs_m < 75:
                        return ("A", "Win") if margin > 0 else ("F", "Loss")
                    else:
                        return ("A+", "Win") if margin > 0 else ("F", "Loss")

                grade_a, label_a = grade_and_label(margin_a)
                grade_b, label_b = grade_and_label(-margin_a)

                at_deal = grade_log.get(tx_id)
                if at_deal is None and date_str >= today_str:
                    at_deal = {"date": date_str, "grade_a": grade_a, "grade_b": grade_b}
                    grade_log[tx_id] = at_deal
                    log_dirty = True

                rows.append({
                    "Season": season, "Week": wk, "Date": date_str,
                    "Team A": side_data[side_a]["team"], "Received A": side_data[side_a]["assets"],
                    "Value A": val_a, "Grade A": grade_a, "Result A": label_a,
                    "Team B": side_data[side_b]["team"], "Received B": side_data[side_b]["assets"],
                    "Value B": val_b, "Grade B": grade_b, "Result B": label_b,
                    "Value Gap": abs(val_a - val_b), "Margin %": round(abs(margin_a), 1),
                    "At-Deal Grade A": at_deal["grade_a"] if at_deal else None,
                    "At-Deal Grade B": at_deal["grade_b"] if at_deal else None,
                })

    if log_dirty:
        _save_trade_grade_log(grade_log)

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Value Gap", ascending=False).reset_index(drop=True)
    return df


def build_most_traded_players(seasons: tuple, n: int = 10) -> list:
    """Players who've changed hands via trade the most, with a breakdown of which teams acquired them."""
    all_players = api.get_all_players()
    counts = {}  # pid -> {"total": int, "by_team": {team: int}}

    for season in seasons:
        league_id = api.SEASON_LEAGUE_IDS.get(season)
        if not league_id:
            continue
        try:
            rosters = api.get_rosters(league_id)
            users = api.get_users(league_id)
        except Exception:
            continue
        owner_map = api.build_owner_map(users, rosters)

        seen_tx = set()
        for wk in range(0, 19):
            try:
                txs = api.get_transactions(league_id, wk)
            except Exception:
                continue
            for tx in txs:
                tx_id = tx.get("transaction_id")
                if tx_id in seen_tx or tx.get("status") != "complete" or tx.get("type") != "trade":
                    continue
                seen_tx.add(tx_id)
                adds = tx.get("adds") or {}
                for pid, rid in adds.items():
                    team = owner_map.get(rid, "Unknown")
                    entry = counts.setdefault(pid, {"total": 0, "by_team": {}})
                    entry["total"] += 1
                    entry["by_team"][team] = entry["by_team"].get(team, 0) + 1

    results = []
    for pid, data in counts.items():
        p = all_players.get(pid, {})
        breakdown = sorted(data["by_team"].items(), key=lambda x: x[1], reverse=True)
        results.append({
            "player_id": pid,
            "name": p.get("full_name", pid),
            "position": p.get("position", ""),
            "total": data["total"],
            "breakdown": breakdown,
        })

    results.sort(key=lambda r: r["total"], reverse=True)
    return results[:n]
