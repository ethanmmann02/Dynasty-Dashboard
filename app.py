"""
Nicos Dynasty League - Streamlit App
--------------------------------------
Tabs: Home / Player Profile / Current Season / League History /
Transactions / Rivalries / Record Book / Strength of Schedule /
Draft History
Trade Grades still TBD (dynasty rookie-draft-only version).
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import analytics
import sleeper_api as api

try:
    analytics.snapshot_dynasty_values_if_needed()
except Exception:
    pass

st.set_page_config(page_title="Nicos Dynasty League", layout="wide", page_icon="🏈")

ACCENT = "#1D4ED8"  # blue, swapped in for Bozos' garnet

st.markdown(
    f"""<style>
    h1, h2, h3 {{ color: {ACCENT}; }}
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    header {{visibility: hidden;}}
    .block-container {{padding-top: 2rem; padding-bottom: 2rem; max-width: 1300px;}}

    div[data-testid="stDataFrame"] {{border: 1px solid #E5E7EB; border-radius: 8px; overflow: hidden;}}

    button[data-baseweb="tab"] {{
        font-size: 1rem; font-weight: 600; padding: 10px 18px; color: #6B7280;
    }}
    button[data-baseweb="tab"][aria-selected="true"] {{
        color: {ACCENT}; border-bottom: 3px solid {ACCENT};
    }}
    div[data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 2px solid #E5E7EB; }}

    div[data-testid="stMetric"] {{
        background: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 10px;
        padding: 14px 16px;
    }}
    div[data-testid="stMetricLabel"] {{ font-weight: 600; color: #6B7280; }}
    div[data-testid="stMetricValue"] {{ color: {ACCENT}; }}

    div[data-baseweb="select"] > div {{
        border-radius: 8px; border: 1px solid #E5E7EB;
    }}

    .stButton > button {{
        border-radius: 8px; border: 1px solid {ACCENT}; color: {ACCENT}; font-weight: 600;
    }}
    .stButton > button:hover {{
        background: {ACCENT}; color: white;
    }}

    hr {{ margin: 1.5rem 0; border-color: #E5E7EB; }}
    </style>""",
    unsafe_allow_html=True,
)

CURRENT_SEASON = api.CURRENT_SEASON
CURRENT_LEAGUE_ID = api.CURRENT_LEAGUE_ID
PLAYOFF_CUTOFF_DEFAULT = 6


def _has_games_played(rosters_: list) -> bool:
    for r in rosters_:
        s = r.get("settings", {})
        if (s.get("wins", 0) + s.get("losses", 0) + s.get("ties", 0)) > 0:
            return True
    return False


# ---------------------------------------------------------------------
# Shared data loads - falls back to the last completed season for
# Home/Current Season if the current season has no games played yet.
# ---------------------------------------------------------------------
league = api.get_league(CURRENT_LEAGUE_ID)
users = api.get_users(CURRENT_LEAGUE_ID)
rosters = api.get_rosters(CURRENT_LEAGUE_ID)

DISPLAY_SEASON = CURRENT_SEASON
DISPLAY_LEAGUE_ID = CURRENT_LEAGUE_ID
DISPLAY_LEAGUE = league
DISPLAY_USERS = users
DISPLAY_ROSTERS = rosters
FELL_BACK = False

if not _has_games_played(rosters):
    for season in sorted(api.ALL_SEASONS, reverse=True):
        if season == CURRENT_SEASON:
            continue
        lid = api.SEASON_LEAGUE_IDS[season]
        try:
            r2 = api.get_rosters(lid)
        except Exception:
            continue
        if _has_games_played(r2):
            DISPLAY_SEASON = season
            DISPLAY_LEAGUE_ID = lid
            DISPLAY_LEAGUE = api.get_league(lid)
            DISPLAY_USERS = api.get_users(lid)
            DISPLAY_ROSTERS = r2
            FELL_BACK = True
            break

owner_map = api.build_owner_map(DISPLAY_USERS, DISPLAY_ROSTERS)
roster_by_id = {r["roster_id"]: r for r in DISPLAY_ROSTERS}
owner_id_map = api.build_owner_id_map(DISPLAY_USERS, DISPLAY_ROSTERS)
division_map = analytics.get_division_map(DISPLAY_LEAGUE, DISPLAY_ROSTERS)
PLAYOFF_CUTOFF = DISPLAY_LEAGUE.get("settings", {}).get("playoff_teams", PLAYOFF_CUTOFF_DEFAULT)

PLAYOFF_WEEK_START = DISPLAY_LEAGUE.get("settings", {}).get("playoff_week_start", 15)
if FELL_BACK:
    CURRENT_WEEK = PLAYOFF_WEEK_START - 1
else:
    CURRENT_WEEK = max(1, DISPLAY_LEAGUE.get("settings", {}).get("leg", 1) or 1)

st.title(f"Nicos Dynasty League — {DISPLAY_SEASON}")
if FELL_BACK:
    st.info(
        f"{CURRENT_SEASON} season hasn't kicked off yet — Home and Current Season "
        f"are showing final {DISPLAY_SEASON} results until week 1 games are played."
    )

manager_directory = analytics.get_manager_directory()
season_history = analytics.build_season_history()
weekly_history = analytics.build_full_weekly_history()

tab_home, tab_profile, tab_current, tab_history, tab_txns, tab_rivalries, tab_record, tab_sos, tab_draft, tab_trades = st.tabs(
    ["🏠 Home", "👤 Player Profile", "📅 Current Season", "📚 League History", "🔄 Transactions", "🔥 Rivalries", "📖 Record Book", "📆 Strength of Schedule", "🎯 Draft History", "🤝 Trade History"]
)

# ---------------------------------------------------------------------
# CURRENT SEASON standings df (shared by Home + Current Season tabs)
# ---------------------------------------------------------------------
def build_standings_df() -> pd.DataFrame:
    rows = []
    for r in DISPLAY_ROSTERS:
        settings = r.get("settings", {})
        wins = settings.get("wins", 0)
        losses = settings.get("losses", 0)
        ties = settings.get("ties", 0)
        fpts = settings.get("fpts", 0) + settings.get("fpts_decimal", 0) / 100
        fpts_against = settings.get("fpts_against", 0) + settings.get("fpts_against_decimal", 0) / 100
        games = wins + losses + ties
        rows.append(
            {
                "Roster ID": r["roster_id"], "Player": owner_map.get(r["roster_id"], "Unknown"),
                "Division": division_map.get(r["roster_id"]),
                "W": wins, "L": losses, "T": ties,
                "Win%": round(wins / games, 3) if games else 0.0,
                "Points For": round(fpts, 1), "Points Against": round(fpts_against, 1),
                "PPG": round(fpts / games, 1) if games else 0.0,
            }
        )
    df = pd.DataFrame(rows).sort_values(by=["W", "Points For"], ascending=[False, False]).reset_index(drop=True)
    df.insert(0, "Rank", range(1, len(df) + 1))
    df["Seed"] = df["Rank"].apply(lambda r: r if r <= PLAYOFF_CUTOFF else None)
    return df


standings_df = build_standings_df()

# PPG+ / All-Play% for the display season, pulled from season_history
season_stats = season_history[season_history["season"] == DISPLAY_SEASON][["roster_id", "PPG+", "All-Play %"]].rename(
    columns={"roster_id": "Roster ID"}
)
standings_df = standings_df.merge(season_stats, on="Roster ID", how="left")

# ---------------------------------------------------------------------
# HOME - power rankings
# ---------------------------------------------------------------------
with tab_home:
    st.subheader("Power Rankings")
    weeks_played = list(range(1, CURRENT_WEEK + 1))
    weekly_df = analytics.get_weekly_results(DISPLAY_LEAGUE_ID, weeks_played)

    if weekly_df.empty:
        st.info("No games played yet, power rankings will populate once week 1 wraps.")
    else:
        pr_df = analytics.compute_power_rankings(weekly_df, owner_map, CURRENT_WEEK)
        prev_rank = {}
        if CURRENT_WEEK > 1:
            prior_df = analytics.compute_power_rankings(weekly_df, owner_map, CURRENT_WEEK - 1)
            prev_rank = dict(zip(prior_df["roster_id"], prior_df["Rank"]))

        week_label = f"through Week {CURRENT_WEEK}" if not FELL_BACK else "final regular season"
        st.caption(
            f"{DISPLAY_SEASON} season, {week_label} — weighted 30% overall record, 22% overall PPG, "
            "18% last-5 record, 12% last-5 PPG, 10% last-3 record, 8% last-3 PPG."
        )
        rank_colors = {1: "#F59E0B", 2: "#9CA3AF", 3: "#B45309"}
        for _, row in pr_df.iterrows():
            move = ""
            if row["roster_id"] in prev_rank:
                delta = prev_rank[row["roster_id"]] - row["Rank"]
                if delta > 0:
                    move = f"<span style='color:#16A34A;font-weight:700;font-size:.85rem;'>▲ {delta}</span>"
                elif delta < 0:
                    move = f"<span style='color:#DC2626;font-weight:700;font-size:.85rem;'>▼ {abs(delta)}</span>"
                else:
                    move = "<span style='color:#9CA3AF;font-size:.85rem;'>—</span>"
            rank_int = int(row["Rank"])
            badge_color = rank_colors.get(rank_int, "#E5E7EB")
            badge_text = "#FFFFFF" if rank_int in rank_colors else "#374151"
            st.markdown(
                f"""<div style='display:flex;align-items:center;justify-content:space-between;
                background:#FFFFFF;border:1px solid #E5E7EB;border-left:4px solid {ACCENT};
                border-radius:10px;padding:14px 18px;margin-bottom:8px;box-shadow:0 1px 2px rgba(0,0,0,0.04);'>
                    <div style='display:flex;align-items:center;gap:14px;'>
                        <div style='background:{badge_color};color:{badge_text};font-weight:800;
                        border-radius:50%;width:32px;height:32px;display:flex;align-items:center;
                        justify-content:center;font-size:.9rem;flex-shrink:0;'>{rank_int}</div>
                        <div>
                            <div style='font-weight:700;font-size:1rem;color:#111827;'>{row['Team']}
                                <span style='font-weight:500;color:#6B7280;'>{row['Record']} · {row['PPG']} PPG</span>
                            </div>
                            <div style='font-size:.8rem;color:#9CA3AF;margin-top:2px;'>
                                L5: {row['L5']} ({row['L5 PPG']} PPG) &nbsp;|&nbsp; L3: {row['L3']} ({row['L3 PPG']} PPG)
                            </div>
                        </div>
                    </div>
                    <div>{move}</div>
                </div>""",
                unsafe_allow_html=True,
            )

# ---------------------------------------------------------------------
# PLAYER PROFILE
# ---------------------------------------------------------------------
with tab_profile:
    st.subheader("Player Profile")

    if season_history.empty:
        st.info("No season history available yet.")
    else:
        owner_ids_with_history = sorted(
            season_history["owner_id"].dropna().unique(), key=lambda oid: manager_directory.get(oid, "Unknown")
        )
        name_by_owner = {oid: manager_directory.get(oid, "Unknown") for oid in owner_ids_with_history}

        c1, c2 = st.columns([2, 3])
        with c1:
            selected_name = st.selectbox("Select player", list(name_by_owner.values()))
            selected_owner_id = next(oid for oid, name in name_by_owner.items() if name == selected_name)
        with c2:
            min_season, max_season = int(season_history["season"].min()), int(season_history["season"].max())
            if min_season == max_season:
                season_range = (min_season, max_season)
                st.caption(f"Season: {min_season}")
            else:
                season_range = st.slider("Season range", min_value=min_season, max_value=max_season, value=(min_season, max_season))

        career = analytics.build_manager_career(selected_owner_id, season_range, season_history, weekly_history)

        def _mini_card(col, label, value):
            col.markdown(
                f"""<div style='background:linear-gradient(180deg,rgba(255,255,255,.96),rgba(239,246,255,.96));
                border:1px solid rgba(29,78,216,.15);padding:16px 18px;border-radius:18px;box-shadow:0 8px 24px rgba(29,78,216,.06);'>
                <div style='font-size:.82rem;font-weight:700;color:#64748b;line-height:1.3;'>{label}</div>
                <div style='font-size:2rem;font-weight:700;margin-top:6px;color:{ACCENT};'>{value}</div>
                </div>""",
                unsafe_allow_html=True,
            )

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        _mini_card(c1, "Championships", career["championships"])
        _mini_card(c2, "Championship<br>Appearances", career["championship_appearances"])
        _mini_card(c3, "Playoff Appearances", career["playoff_apps"])
        _mini_card(c4, "Division Titles", career["division_titles"])
        _mini_card(c5, "Avg PPG", career["avg_ppg"] if career["avg_ppg"] else "—")
        _mini_card(c6, "Total Regular-<br>Season Wins", career["total_wins"])

        st.markdown("---")
        left, right = st.columns([3, 2])
        with left:
            chart_mode = st.radio("Chart", ["Wins", "Points Scored", "Both"], horizontal=True)
            cdf = career["career_df"]
            if cdf.empty:
                st.caption("No data for this season range.")
            else:
                fig = go.Figure()
                if chart_mode in ("Wins", "Both"):
                    fig.add_trace(go.Scatter(x=cdf["season"], y=cdf["W"], mode="lines+markers", name="Wins", line=dict(color=ACCENT, width=3)))
                if chart_mode in ("Points Scored", "Both"):
                    fig.add_trace(go.Scatter(x=cdf["season"], y=cdf["PF"], mode="lines+markers", name="Points", line=dict(color="#F59E0B", width=3),
                                              yaxis="y2" if chart_mode == "Both" else "y1"))
                layout_kwargs = dict(height=380, margin=dict(l=10, r=10, t=30, b=10), xaxis=dict(dtick=1),
                                      title="Wins by season" if chart_mode == "Wins" else ("Points scored by season" if chart_mode == "Points Scored" else "Wins & Points by season"))
                if chart_mode == "Both":
                    layout_kwargs["yaxis"] = dict(title="Wins")
                    layout_kwargs["yaxis2"] = dict(title="Points", overlaying="y", side="right")
                fig.update_layout(**layout_kwargs)
                st.plotly_chart(fig, width="stretch")

        with right:
            st.markdown("**Player Summary**")
            summary_rows = [
                ("Seasons", f"{season_range[0]}-{season_range[1]}"),
                ("Seasons Played", career["seasons_played"]),
                ("Total Wins", career["total_wins"]),
                ("Total Losses", career["total_losses"]),
                ("Total Points", career["total_points"]),
                ("Avg PPG+", career["avg_ppg_plus"] if career["avg_ppg_plus"] is not None else "—"),
                ("Avg All-Play %", career["avg_all_play_pct"] if career["avg_all_play_pct"] is not None else "—"),
                ("Playoff Wins", career["playoff_wins"]),
                ("Playoff Losses", career["playoff_losses"]),
            ]
            st.dataframe(pd.DataFrame([(m, str(v)) for m, v in summary_rows], columns=["Metric", "Value"]), width="stretch", hide_index=True)

        st.markdown("---")
        st.markdown("**Season-by-season stats**")
        cdf_display = career["career_df"][["season", "W", "L", "PF", "PA", "PPG", "PPG+", "All-Play %", "Seed", "Made Playoffs", "Champion", "Runner-Up"]].rename(
            columns={"season": "Season", "PF": "Points For", "PA": "Points Against", "Made Playoffs": "Playoffs", "Champion": "Champ"}
        )
        st.dataframe(cdf_display, width="stretch", hide_index=True)

        st.markdown("---")
        st.markdown("**Head-to-head summary**")
        h2h_weekly = weekly_history[(weekly_history["season"] >= season_range[0]) & (weekly_history["season"] <= season_range[1])]
        h2h_df = analytics.build_h2h_summary(h2h_weekly, selected_owner_id)
        if h2h_df.empty:
            st.caption("No head-to-head games in this range.")
        else:
            st.dataframe(h2h_df.drop(columns=["opp_owner_id"]), width="stretch", hide_index=True)

        st.markdown("---")
        st.markdown("**Key Offseason Moves**")
        prior_season = CURRENT_SEASON - 1
        if prior_season in api.ALL_SEASONS:
            roster_diff = analytics.build_roster_diff(CURRENT_SEASON, prior_season)
            moves = roster_diff.get(selected_owner_id, {"added": [], "removed": []})
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Added**")
                if moves["added"]:
                    for m in moves["added"]:
                        tag = " 🆕 rookie" if m.get("rookie") else ""
                        st.markdown(f"+ {m['name']} ({m['pos']}, {m['team']}){tag}")
                else:
                    st.caption("No notable offseason adds.")
            with c2:
                st.markdown("**Removed**")
                if moves["removed"]:
                    for m in moves["removed"]:
                        st.markdown(f"− {m['name']} ({m['pos']}, {m['team']})")
                else:
                    st.caption("No notable offseason drops.")
            st.caption(f"Comparing {CURRENT_SEASON} roster to final {prior_season} roster — net roster moves only, not raw transactions.")

        st.markdown("---")
        st.markdown("**Dynasty Value**")
        try:
            cur_rosters_for_value = api.get_rosters(CURRENT_LEAGUE_ID)
            cur_roster_for_owner = next((r for r in cur_rosters_for_value if r.get("owner_id") == selected_owner_id), None)
        except Exception:
            cur_roster_for_owner = None

        POSITION_COLORS = {"QB": "#DC2626", "RB": "#059669", "WR": "#1D4ED8", "TE": "#D97706", "K": "#6B7280", "DEF": "#0891B2"}
        TIER_COLORS = {"Elite": "#D97706", "Core": "#1D4ED8", "Flex": "#0EA5E9", "Depth": "#6B7280", "Lottery": "#7C3AED"}

        if not cur_roster_for_owner or not cur_roster_for_owner.get("players"):
            st.caption("No current roster found for this manager.")
        else:
            all_players_dv = api.get_all_players()
            dv = analytics.build_dynasty_value_breakdown(cur_roster_for_owner["players"], all_players_dv)
            if not dv:
                st.caption(
                    "Dynasty values aren't showing right now — either FantasyCalc's API didn't return anything or "
                    "player IDs didn't match. This is a first pass at this feature (external data source I couldn't "
                    "test from my end), flag it if it stays empty and I'll dig into the field mapping."
                )
            else:
                dv_left, dv_right = st.columns([3, 2])
                with dv_left:
                    pie_colors = [POSITION_COLORS.get(r["position"], "#6B7280") for r in dv["position_rows"]]
                    pos_fig = go.Figure(
                        go.Pie(
                            labels=[r["position"] for r in dv["position_rows"]],
                            values=[r["value"] for r in dv["position_rows"]],
                            hole=0.65,
                            marker=dict(colors=pie_colors, line=dict(color="white", width=2)),
                            textinfo="label+percent",
                            textfont=dict(size=13, color="white"),
                        )
                    )
                    pos_fig.update_layout(
                        height=300, margin=dict(l=10, r=10, t=10, b=10), showlegend=False,
                        annotations=[dict(text=f"<b>{dv['total_value']:,}</b><br><span style='font-size:11px;color:#64748b;'>TOTAL VALUE</span>",
                                           x=0.5, y=0.5, font=dict(size=20), showarrow=False)],
                    )
                    st.plotly_chart(pos_fig, width="stretch")

                with dv_right:
                    st.markdown("**By Position**")
                    league_dv_df = analytics.build_league_dynasty_value_table()
                    max_val = max(r["value"] for r in dv["position_rows"])
                    for row in dv["position_rows"]:
                        color = POSITION_COLORS.get(row["position"], "#6B7280")
                        bar_pct = round(row["value"] / max_val * 100)
                        rank_info = analytics.get_position_rank(league_dv_df, selected_owner_id, row["position"])
                        rank_str = f" · #{rank_info[0]}/{rank_info[1]}" if rank_info else ""
                        st.markdown(
                            f"""<div style='margin-bottom:10px;'>
                            <div style='display:flex;justify-content:space-between;font-size:.85rem;font-weight:600;'>
                                <span><span style='display:inline-block;width:10px;height:10px;border-radius:3px;background:{color};margin-right:6px;'></span>{row['position']}</span>
                                <span style='color:#64748b;'>{row['share']}% · {row['value']:,}{rank_str}</span>
                            </div>
                            <div style='background:#E5E7EB;border-radius:4px;height:6px;margin-top:4px;'>
                                <div style='background:{color};width:{bar_pct}%;height:6px;border-radius:4px;'></div>
                            </div>
                            </div>""",
                            unsafe_allow_html=True,
                        )

                st.markdown("**Asset Tier Breakdown**")
                tier_cols = st.columns(len(dv["tier_rows"]))
                for col, tier in zip(tier_cols, dv["tier_rows"]):
                    color = TIER_COLORS.get(tier["tier"], "#6B7280")
                    assets_html = "".join(
                        f"<div style='font-size:.78rem;color:#374151;margin-top:4px;'>{a['name']} <span style='color:#9CA3AF;'>({a['position']}, {a['value']:,})</span></div>"
                        for a in tier["top_assets"]
                    )
                    with col:
                        st.markdown(
                            f"""<div style='border-top:4px solid {color};background:#F9FAFB;border-radius:0 0 10px 10px;
                            padding:12px 10px;height:100%;'>
                            <div style='font-weight:800;color:{color};font-size:.9rem;'>{tier['tier']}</div>
                            <div style='font-size:.78rem;color:#6B7280;margin-bottom:6px;'>{tier['share']}% · {tier['count']} assets</div>
                            {assets_html if assets_html else "<div style='font-size:.78rem;color:#9CA3AF;'>—</div>"}
                            </div>""",
                            unsafe_allow_html=True,
                        )

                st.caption(
                    "Values pulled live from FantasyCalc (12-team, 1QB dynasty format), external to Sleeper. "
                    "Draft picks aren't valued yet — next pass."
                )

                st.markdown("**Biggest Risers & Droppers**")
                movers = analytics.build_value_movers_v2(cur_roster_for_owner["players"], all_players_dv)

                if movers.get("note"):
                    st.caption(movers["note"])

                if not movers["risers"] and not movers["droppers"]:
                    pass
                else:
                    mv_left, mv_right = st.columns(2)
                    with mv_left:
                        st.markdown("🔺 **Risers**")
                        if not movers["risers"]:
                            st.caption("None right now.")
                        for a in movers["risers"]:
                            ic1, ic2 = st.columns([1, 4])
                            with ic1:
                                st.image(f"https://sleepercdn.com/content/nfl/players/{a['player_id']}.jpg", width=48)
                            with ic2:
                                st.markdown(f"**{a['name']}** ({a['position']})")
                                st.caption(f"{a['value']:,} · <span style='color:#16A34A;'>+{a['change']:,}</span>", unsafe_allow_html=True)
                    with mv_right:
                        st.markdown("🔻 **Droppers**")
                        if not movers["droppers"]:
                            st.caption("None right now.")
                        for a in movers["droppers"]:
                            ic1, ic2 = st.columns([1, 4])
                            with ic1:
                                st.image(f"https://sleepercdn.com/content/nfl/players/{a['player_id']}.jpg", width=48)
                            with ic2:
                                st.markdown(f"**{a['name']}** ({a['position']})")
                                st.caption(f"{a['value']:,} · <span style='color:#DC2626;'>{a['change']:,}</span>", unsafe_allow_html=True)


# ---------------------------------------------------------------------
# CURRENT SEASON - standings + in the hunt + playoff bracket, one page
# ---------------------------------------------------------------------
def seed_label(roster_id):
    if roster_id is None:
        return "TBD"
    return owner_map.get(roster_id, f"Roster {roster_id}")


with tab_current:
    st.subheader(f"{DISPLAY_SEASON} standings")
    display_cols = ["Rank", "Seed", "Division", "Player", "W", "L", "Points For", "Points Against", "PPG", "PPG+", "All-Play %"]
    show_cols = [c for c in display_cols if c in standings_df.columns]
    st.dataframe(standings_df[show_cols], width="stretch", hide_index=True)

    st.markdown("---")
    st.subheader("In the hunt")
    bubble_df = standings_df[standings_df["Rank"] > PLAYOFF_CUTOFF].copy()
    if bubble_df.empty:
        st.caption("Everyone still in the field, or not enough games played yet.")
    else:
        cutoff_row = standings_df[standings_df["Rank"] == PLAYOFF_CUTOFF]
        if not cutoff_row.empty:
            leader_w, leader_l = cutoff_row["W"].iloc[0], cutoff_row["L"].iloc[0]
            leader_pf = cutoff_row["Points For"].iloc[0]
            bubble_df["Games Back"] = bubble_df.apply(
                lambda r: round(((leader_w - r["W"]) + (r["L"] - leader_l)) / 2, 1), axis=1
            )
            bubble_df[f"Points vs #{PLAYOFF_CUTOFF}"] = round(bubble_df["Points For"] - leader_pf, 2)
        hunt_display = bubble_df[["Rank", "Player", "W", "L", "Games Back", f"Points vs #{PLAYOFF_CUTOFF}"]]
        st.dataframe(hunt_display, width="stretch", hide_index=True)

    st.markdown("---")
    st.subheader("Playoff bracket")
    try:
        bracket = analytics.filter_real_bracket_matches(api.get_winners_bracket(DISPLAY_LEAGUE_ID))
    except Exception:
        bracket = []

    if not bracket or all(m.get("t1") is None and m.get("t2") is None for m in bracket):
        st.info(f"Bracket isn't set yet — this fills in once the regular season wraps (playoffs start week {PLAYOFF_WEEK_START}).")
    else:
        by_round = {}
        for m in bracket:
            by_round.setdefault(m["r"], []).append(m)
        winner_of = {m["m"]: m.get("w") for m in bracket}

        def resolve_team(m, side):
            direct = m.get(f"t{side}")
            if direct is not None:
                return seed_label(direct)
            src = m.get(f"t{side}_from", {})
            if src.get("w") is not None:
                w = winner_of.get(src["w"])
                return seed_label(w) if w else f"Winner of M{src['w']}"
            if src.get("l") is not None:
                return f"Loser of M{src['l']}"
            return "TBD"

        round_names = {1: "Quarterfinals", 2: "Semifinals", 3: "Championship"}
        cols = st.columns(len(by_round))
        for col, r in zip(cols, sorted(by_round.keys())):
            with col:
                st.markdown(f"**{round_names.get(r, f'Round {r}')}**")
                for m in by_round[r]:
                    t1, t2 = resolve_team(m, 1), resolve_team(m, 2)
                    winner_id = m.get("w")
                    t1_won = winner_id is not None and m.get("t1") == winner_id
                    t2_won = winner_id is not None and m.get("t2") == winner_id
                    t1_disp = f"**{t1}** ✅" if t1_won else t1
                    t2_disp = f"**{t2}** ✅" if t2_won else t2
                    st.markdown(
                        f"<div style='border:1px solid {ACCENT}55;border-radius:8px;padding:8px 12px;margin-bottom:10px;'>{t1_disp}<br>vs<br>{t2_disp}</div>",
                        unsafe_allow_html=True,
                    )
    st.caption("Top 2 seeds get a first-round bye and stay on their side of the bracket (4 vs 5 feeds into 1, 3 vs 6 feeds into 2).")

# ---------------------------------------------------------------------
# LEAGUE HISTORY - multi-season compare table
# ---------------------------------------------------------------------
with tab_history:
    st.subheader("League history")
    if season_history.empty:
        st.info("No season history available yet.")
    else:
        all_seasons_sorted = sorted(season_history["season"].unique())
        selected_seasons = st.multiselect("Select seasons to compare", all_seasons_sorted, default=all_seasons_sorted)
        compare_df = analytics.build_league_history_table(selected_seasons, season_history, weekly_history, manager_directory)
        st.dataframe(compare_df, width="stretch", hide_index=True)

        st.markdown("---")
        st.subheader("Top single-week scores")
        owner_ids_with_history = sorted(season_history["owner_id"].dropna().unique(), key=lambda oid: manager_directory.get(oid, "Unknown"))
        name_by_owner_hist = {oid: manager_directory.get(oid, "Unknown") for oid in owner_ids_with_history}
        pick_team_hist = st.selectbox("Pick a team", ["League-wide"] + list(name_by_owner_hist.values()), key="history_top_scores_team")
        hist_weekly = weekly_history[weekly_history["season"].isin(selected_seasons)]
        if pick_team_hist == "League-wide":
            hist_top_scores = analytics.build_top_scores(hist_weekly, owner_id=None)
        else:
            hist_oid = next(o for o, n in name_by_owner_hist.items() if n == pick_team_hist)
            hist_top_scores = analytics.build_top_scores(hist_weekly, owner_id=hist_oid)
        st.dataframe(hist_top_scores, width="stretch", hide_index=True)

# ---------------------------------------------------------------------
# TRANSACTIONS
# ---------------------------------------------------------------------
with tab_txns:
    st.subheader("Transactions")
    all_seasons_sorted = sorted(api.ALL_SEASONS)
    sel_years = st.multiselect("Years", all_seasons_sorted, default=all_seasons_sorted)
    team_names = ["All"] + sorted(manager_directory.values())
    sel_team = st.selectbox("Team", team_names)
    sel_types = st.multiselect("Transaction types", ["Free Agent", "Trade", "Waiver"], default=["Free Agent", "Trade", "Waiver"])

    if not sel_years:
        st.info("Pick at least one year.")
    else:
        txn_df = analytics.build_transactions_log(tuple(sel_years))
        if txn_df.empty:
            st.info("No transactions found for this selection.")
        else:
            completed = txn_df[txn_df["Status"] == "Complete"]
            filtered = completed[completed["Type"].isin(sel_types)]
            if sel_team != "All":
                filtered = filtered[filtered["Team"] == sel_team]
            display_cols = ["Season", "Week", "Date", "Type", "Team", "With", "FAAB", "Summary"]
            st.dataframe(filtered[display_cols], width="stretch", hide_index=True)

            if sel_team != "All":
                st.markdown("---")
                st.subheader(f"Trade counts for {sel_team}")
                # trade counts pull from ALL seasons regardless of the Years
                # filter above, same as Bozos - it's a career stat
                all_txn_df = analytics.build_transactions_log(tuple(sorted(api.ALL_SEASONS)))
                sel_owner_id = next((oid for oid, name in manager_directory.items() if name == sel_team), None)
                trade_counts_df = analytics.build_trade_counts(all_txn_df, sel_owner_id) if sel_owner_id else pd.DataFrame()
                if trade_counts_df.empty:
                    st.caption("No trades on record for this manager.")
                else:
                    st.dataframe(trade_counts_df, width="stretch", hide_index=True)

            st.markdown("---")
            st.subheader("Failed bids")
            failed_df = analytics.build_failed_bids(tuple(sel_years))
            if sel_team != "All":
                failed_df = failed_df[failed_df["Team"] == sel_team]
            if failed_df.empty:
                st.caption("No failed waiver bids in this selection.")
            else:
                st.dataframe(failed_df, width="stretch", hide_index=True)
                st.caption("\"Went To\" is the closest completed waiver add for that same player - if nothing lines up it shows Unresolved.")

            st.markdown("---")
            st.subheader("FAAB spending")
            faab_stats = analytics.build_faab_stats(completed)
            if not faab_stats:
                st.caption("No FAAB waiver activity in this selection.")
            else:
                fc1, fc2 = st.columns(2)
                fc1.metric("Avg FAAB per winning bid", faab_stats["avg_faab"])
                fc2.metric(
                    "Biggest single bid",
                    f"{int(faab_stats['biggest_bid']['FAAB'])}",
                    help=f"{faab_stats['biggest_bid']['Team']} — {faab_stats['biggest_bid']['Summary']}",
                )
                fc_left, fc_right = st.columns(2)
                with fc_left:
                    st.markdown("**By season**")
                    st.dataframe(faab_stats["by_season"], width="stretch", hide_index=True)
                with fc_right:
                    st.markdown("**By team**")
                    st.dataframe(faab_stats["by_team"], width="stretch", hide_index=True)

            st.markdown("---")
            st.subheader("Best waiver wire adds")
            st.caption("Waiver/free agent pickups ranked by their CURRENT dynasty value - the actual all-time hits, not just this year's.")
            waiver_detail_df = analytics.build_waiver_adds_detail(tuple(sorted(api.ALL_SEASONS)))
            best_add_owner_id = next((oid for oid, name in manager_directory.items() if name == sel_team), None) if sel_team != "All" else None
            best_waiver_df = analytics.build_best_waiver_adds(waiver_detail_df, owner_id=best_add_owner_id)
            if best_waiver_df.empty:
                st.caption("Nothing to show here yet (needs FantasyCalc data).")
            else:
                st.dataframe(best_waiver_df, width="stretch", hide_index=True)

# ---------------------------------------------------------------------
# RIVALRIES
# ---------------------------------------------------------------------
with tab_rivalries:
    st.subheader("Rivalries")
    st.markdown("**Head-to-head matrix**")
    st.caption("Win% for the row manager against the column manager, across all tracked seasons (independent of any season filter elsewhere). Blank = no games played.")

    names, z, text = analytics.build_h2h_heatmap(weekly_history, manager_directory)
    heat_fig = go.Figure(
        data=go.Heatmap(
            z=z, x=names, y=names, text=text, texttemplate="%{text}",
            colorscale="RdYlGn", zmin=0, zmax=100,
            colorbar=dict(title="Win %"),
            hovertemplate="%{y} vs %{x}: %{text} (%{z}%)<extra></extra>",
        )
    )
    heat_fig.update_layout(height=max(400, 32 * len(names)), margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(autorange="reversed"))
    st.plotly_chart(heat_fig, width="stretch")

    st.markdown("---")
    min_games = st.slider("Minimum games for a rivalry to count", 1, 10, 3)
    view_choice = st.radio("View", ["All rivalries", "Pick a manager"], horizontal=True)

    if view_choice == "All rivalries":
        league_riv_df = analytics.build_league_wide_rivalries(weekly_history, manager_directory, min_games)
        if league_riv_df.empty:
            st.caption("Not enough head-to-head history yet.")
        else:
            st.dataframe(league_riv_df, width="stretch", hide_index=True)
    else:
        owner_ids_with_history = sorted(season_history["owner_id"].dropna().unique(), key=lambda oid: manager_directory.get(oid, "Unknown"))
        name_by_owner = {oid: manager_directory.get(oid, "Unknown") for oid in owner_ids_with_history}
        selected_name = st.selectbox("Manager", list(name_by_owner.values()), key="rivalry_manager")
        selected_owner_id = next(oid for oid, name in name_by_owner.items() if name == selected_name)
        riv_df = analytics.build_rivalry_table(weekly_history, selected_owner_id, min_games)
        if riv_df.empty:
            st.caption("Not enough head-to-head history yet.")
        else:
            st.dataframe(riv_df, width="stretch", hide_index=True)

    st.caption(
        "Rivalry Index (0-100) blends series balance, game closeness, playoff weight, and volume of meetings. "
        "This is a reconstruction of the Bozos formula's intent, not its exact weights — flag any results that look off and we'll retune it."
    )

# ---------------------------------------------------------------------
# RECORD BOOK
# ---------------------------------------------------------------------
with tab_record:
    st.subheader("Championship banners")
    champs = season_history[season_history["Champion"]][["season", "Team"]].sort_values("season", ascending=False)
    if champs.empty:
        st.caption("No champion decided yet for any tracked season.")
    else:
        cols = st.columns(len(champs))
        colors = ["#1D4ED8", "#7C3AED", "#059669", "#DC2626", "#65A30D", "#EA580C"]
        for i, (col, (_, row)) in enumerate(zip(cols, champs.iterrows())):
            color = colors[i % len(colors)]
            with col:
                st.markdown(
                    f"""<div style='background:linear-gradient(180deg,{color},{color}CC);border-radius:8px;
                    padding:24px 12px;text-align:center;color:white;box-shadow:0 8px 20px rgba(0,0,0,.15);'>
                    <div style='font-size:.75rem;letter-spacing:1px;opacity:.85;'>CHAMPION</div>
                    <div style='font-size:1.4rem;font-weight:800;margin:8px 0;'>{row['Team']}</div>
                    <div style='font-size:.95rem;opacity:.9;'>{row['season']}</div>
                    </div>""",
                    unsafe_allow_html=True,
                )

    st.markdown("---")
    st.subheader("Top single-week scores")
    owner_ids_with_history = sorted(season_history["owner_id"].dropna().unique(), key=lambda oid: manager_directory.get(oid, "Unknown"))
    name_by_owner = {oid: manager_directory.get(oid, "Unknown") for oid in owner_ids_with_history}
    pick_team = st.selectbox("Pick a team", ["League-wide"] + list(name_by_owner.values()))
    if pick_team == "League-wide":
        top_scores = analytics.build_top_scores(weekly_history, owner_id=None)
    else:
        oid = next(o for o, n in name_by_owner.items() if n == pick_team)
        top_scores = analytics.build_top_scores(weekly_history, owner_id=oid)
    st.dataframe(top_scores, width="stretch", hide_index=True)

    st.markdown("---")
    st.subheader("Best single-season PPG")
    best_ppg = season_history.sort_values("PPG", ascending=False).head(15)
    best_ppg_display = best_ppg[["season", "Team", "PPG", "PPG+", "W", "L", "PF", "PA"]].rename(
        columns={"season": "Season", "Team": "Player", "PF": "Points For", "PA": "Points Against"}
    )
    st.dataframe(best_ppg_display, width="stretch", hide_index=True)

    st.markdown("---")
    st.subheader("Longest winning / losing streaks")
    streaks_df = analytics.build_streaks(weekly_history, manager_directory)
    st.dataframe(streaks_df, width="stretch", hide_index=True)

# ---------------------------------------------------------------------
# STRENGTH OF SCHEDULE
# ---------------------------------------------------------------------
with tab_sos:
    st.subheader("Strength of schedule")
    st.caption("Regular season only.")
    if season_history.empty:
        st.info("No season history available yet.")
    else:
        all_seasons_sorted = sorted(season_history["season"].unique())
        sel_seasons = st.multiselect("Seasons", all_seasons_sorted, default=[max(all_seasons_sorted)])
        view_mode = st.radio("View", ["Split by season", "Join all seasons"], horizontal=True)

        if not sel_seasons:
            st.info("Pick at least one season.")
        else:
            if view_mode == "Join all seasons":
                sos_df = analytics.build_strength_of_schedule((min(sel_seasons), max(sel_seasons)))
                sos_df = sos_df[sos_df["Team"].notna()] if not sos_df.empty else sos_df
            else:
                frames = []
                for s in sel_seasons:
                    d = analytics.build_strength_of_schedule((s, s))
                    if not d.empty:
                        d.insert(0, "Season", s)
                        frames.append(d)
                sos_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

            if sos_df.empty:
                st.info("No games played in this selection yet.")
            else:
                cols = (["Season"] if "Season" in sos_df.columns else []) + ["Team", "Games", "PPG", "Opp PPG", "Net Margin", "PPG+", "W", "L", "Expected W", "Luck (+/-)"]
                st.dataframe(sos_df[cols], width="stretch", hide_index=True)

                st.markdown("---")
                fig = go.Figure(
                    go.Scatter(
                        x=sos_df["Opp PPG"], y=sos_df["PPG"], mode="markers+text", text=sos_df["Team"], textposition="top center",
                        marker=dict(size=10, color=ACCENT),
                    )
                )
                x_mid, y_mid = sos_df["Opp PPG"].mean(), sos_df["PPG"].mean()
                fig.add_vline(x=x_mid, line_dash="dash", line_color="gray")
                fig.add_hline(y=y_mid, line_dash="dash", line_color="gray")
                fig.add_annotation(x=sos_df["Opp PPG"].min(), y=sos_df["PPG"].max(), text="Good team,<br>easy schedule", showarrow=False, font=dict(size=11, color="gray"))
                fig.add_annotation(x=sos_df["Opp PPG"].max(), y=sos_df["PPG"].max(), text="Good team,<br>hard schedule", showarrow=False, font=dict(size=11, color="gray"))
                fig.update_layout(
                    xaxis_title="Opponent PPG (strength of schedule)", yaxis_title="Own PPG (team quality)",
                    height=560, margin=dict(l=10, r=10, t=40, b=10),
                )
                st.plotly_chart(fig, width="stretch")

                st.caption(
                    "Expected wins are based on an all-play record — each week, a team's score is compared against every "
                    "other team's score that week, not just their actual opponent. Positive luck means outperforming their "
                    "scoring; negative means the schedule cost them wins their scoring deserved."
                )


# ---------------------------------------------------------------------
# TRADE HISTORY - hindsight grades using current FantasyCalc values
# ---------------------------------------------------------------------
with tab_trades:
    st.subheader("Trade History")
    st.caption(
        "Grades use TODAY's FantasyCalc values applied to both sides, not values at the time of the trade "
        "(FantasyCalc doesn't expose historical data) - so this is a hindsight read, not a trade-day fairness call. "
        "Picks already drafted are valued as the actual player taken; picks marked * are still in the future and use "
        "a standard round-based estimate."
    )

    trades_df = analytics.build_trade_grades(tuple(api.ALL_SEASONS), CURRENT_SEASON)

    if trades_df.empty:
        st.info("No completed trades found yet.")
    else:
        grade_colors = {
            "A+": "#065F46", "A": "#16A34A", "A-": "#4ADE80",
            "B": "#84CC16", "C": "#9CA3AF",
            "D-": "#FB923C", "D": "#EA580C", "F": "#991B1B",
        }

        def grade_badge(grade, faded=False):
            color = grade_colors.get(grade, "#9CA3AF")
            opacity = "0.45" if faded else "1"
            return (f"<span style='background:{color};color:white;font-weight:800;border-radius:6px;"
                    f"padding:2px 9px;font-size:.85rem;opacity:{opacity};'>{grade}</span>")

        def trade_card(row):
            at_deal_a = row.get("At-Deal Grade A")
            at_deal_b = row.get("At-Deal Grade B")
            badges_a = grade_badge(row["Grade A"])
            badges_b = grade_badge(row["Grade B"])
            if at_deal_a and at_deal_a != row["Grade A"]:
                badges_a = grade_badge(at_deal_a, faded=True) + " → " + badges_a
            if at_deal_b and at_deal_b != row["Grade B"]:
                badges_b = grade_badge(at_deal_b, faded=True) + " → " + badges_b

            st.markdown(
                f"""<div style='background:#FFFFFF;border:1px solid #E5E7EB;border-radius:10px;
                padding:16px 18px;margin-bottom:10px;box-shadow:0 1px 2px rgba(0,0,0,0.04);'>
                <div style='font-size:.78rem;color:#9CA3AF;margin-bottom:8px;'>{row['Season']} · Week {row['Week']} · {row['Date']}</div>
                <div style='display:flex;gap:24px;flex-wrap:wrap;'>
                    <div style='flex:1;min-width:220px;'>
                        <div style='display:flex;align-items:center;gap:8px;margin-bottom:4px;'>
                            {badges_a}
                            <span style='font-weight:700;'>{row['Team A']}</span>
                            <span style='color:#6B7280;font-size:.8rem;'>{row['Result A']} · {row['Value A']:,}</span>
                        </div>
                        <div style='font-size:.82rem;color:#374151;'>{row['Received A']}</div>
                    </div>
                    <div style='flex:1;min-width:220px;'>
                        <div style='display:flex;align-items:center;gap:8px;margin-bottom:4px;'>
                            {badges_b}
                            <span style='font-weight:700;'>{row['Team B']}</span>
                            <span style='color:#6B7280;font-size:.8rem;'>{row['Result B']} · {row['Value B']:,}</span>
                        </div>
                        <div style='font-size:.82rem;color:#374151;'>{row['Received B']}</div>
                    </div>
                </div>
                </div>""",
                unsafe_allow_html=True,
            )

        st.markdown("**Most Lopsided Trades**")
        for _, row in trades_df.head(5).iterrows():
            trade_card(row)

        st.markdown("---")
        st.markdown("**Most Commonly Traded Players**")
        most_traded = analytics.build_most_traded_players(tuple(api.ALL_SEASONS))
        if not most_traded:
            st.caption("No trade data yet.")
        else:
            mt_cols = st.columns(2)
            for i, p in enumerate(most_traded):
                breakdown_str = ", ".join(f"{team} ({cnt}x)" for team, cnt in p["breakdown"])
                with mt_cols[i % 2]:
                    st.markdown(
                        f"""<div style='background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;
                        padding:10px 14px;margin-bottom:8px;'>
                        <div style='font-weight:700;'>{p['name']} <span style='color:#6B7280;font-weight:500;'>({p['position']})</span>
                        <span style='float:right;color:#1D4ED8;font-weight:800;'>{p['total']}x traded</span></div>
                        <div style='font-size:.78rem;color:#6B7280;margin-top:4px;'>Acquired by: {breakdown_str}</div>
                        </div>""",
                        unsafe_allow_html=True,
                    )

        st.markdown("---")
        st.markdown("**Browse All Trades**")
        team_options = ["All"] + sorted(set(trades_df["Team A"]) | set(trades_df["Team B"]))
        trade_team_filter = st.selectbox("Team", team_options, key="trade_team_filter")
        season_options = ["All"] + sorted(trades_df["Season"].unique(), reverse=True)
        trade_season_filter = st.selectbox("Season", season_options, key="trade_season_filter")

        browse_df = trades_df
        if trade_team_filter != "All":
            browse_df = browse_df[(browse_df["Team A"] == trade_team_filter) | (browse_df["Team B"] == trade_team_filter)]
        if trade_season_filter != "All":
            browse_df = browse_df[browse_df["Season"] == trade_season_filter]
        browse_df = browse_df.sort_values("Date", ascending=False)

        if browse_df.empty:
            st.caption("No trades match this filter.")
        else:
            for _, row in browse_df.iterrows():
                trade_card(row)

# ---------------------------------------------------------------------
# DRAFT HISTORY - rookie drafts only (2024 startup draft excluded)
# ---------------------------------------------------------------------
with tab_draft:
    st.subheader("Draft History")
    if not analytics.ROOKIE_DRAFT_SEASONS:
        st.info("No rookie draft seasons tracked yet.")
    else:
        draft_season = st.selectbox("Season", sorted(analytics.ROOKIE_DRAFT_SEASONS, reverse=True))
        draft_df = analytics.build_draft_history(draft_season)

        # all teams for this season, not just ones that happened to draft
        # someone - a team with 0 picks (e.g. traded them all away) should
        # still show up as an option, with an empty table
        season_league_id = api.SEASON_LEAGUE_IDS.get(draft_season)
        try:
            season_rosters = api.get_rosters(season_league_id)
            season_users = api.get_users(season_league_id)
            all_team_names = sorted(api.build_owner_map(season_users, season_rosters).values())
        except Exception:
            all_team_names = sorted(draft_df["Team"].unique()) if not draft_df.empty else []

        if draft_df.empty:
            st.info(f"No draft results found for {draft_season} yet.")

        st.markdown("---")
        st.subheader("Picks by team")
        pick_team_draft = st.selectbox("Team", all_team_names, key="draft_team_pick")
        if not draft_df.empty:
            team_picks = draft_df[draft_df["Team"] == pick_team_draft][["Round", "Pick", "Overall", "Player", "Pos", "NFL Team"]]
            if team_picks.empty:
                st.caption(f"{pick_team_draft} made no picks this draft (traded them all away, or forfeited).")
            else:
                st.dataframe(team_picks, width="stretch", hide_index=True)

        st.markdown("**UDFA Signings**")
        udfa_df = analytics.build_udfa_signings(draft_season)
        team_udfa = udfa_df[udfa_df["Team"] == pick_team_draft] if not udfa_df.empty else udfa_df
        if team_udfa.empty:
            st.caption(f"No UDFA pickups found for {pick_team_draft} this season.")
        else:
            st.dataframe(team_udfa[["Player", "Pos", "NFL Team"]], width="stretch", hide_index=True)

        if not draft_df.empty:
            dv_analysis_for_board = analytics.build_draft_value_analysis(draft_season)
            delta_by_overall = dict(zip(dv_analysis_for_board["Overall"], dv_analysis_for_board["Delta"])) if not dv_analysis_for_board.empty else {}

            st.markdown("---")
            st.subheader("Draft board")
            st.caption(
                "+ / − / E shows whether a player went later, earlier, or about where their CURRENT dynasty value would "
                "suggest (a real draft-day ADP source isn't available, so this is a value-based stand-in, not true ADP)."
            )
            board_pos_colors = {"QB": "#DC2626", "RB": "#059669", "WR": "#1D4ED8", "TE": "#D97706", "K": "#6B7280", "DEF": "#0891B2"}

            html_parts = ["<div style='display:flex;flex-direction:column;gap:16px;'>"]
            for rnd in sorted(draft_df["Round"].unique()):
                round_df = draft_df[draft_df["Round"] == rnd].sort_values("Overall")
                html_parts.append(f"<div><div style='font-weight:800;color:#374151;margin-bottom:8px;'>Round {int(rnd)}</div>")
                html_parts.append("<div style='display:grid;grid-template-columns:repeat(auto-fill, minmax(160px, 1fr));gap:8px;'>")
                for _, p in round_df.iterrows():
                    color = board_pos_colors.get(p["Pos"], "#6B7280")
                    delta = delta_by_overall.get(p["Overall"])
                    if delta is None:
                        badge = "<span style='color:#9CA3AF;'>—</span>"
                    elif delta >= 3:
                        badge = f"<span style='color:#16A34A;font-weight:800;'>+{delta}</span>"
                    elif delta <= -3:
                        badge = f"<span style='color:#DC2626;font-weight:800;'>{delta}</span>"
                    else:
                        badge = "<span style='color:#6B7280;font-weight:800;'>E</span>"
                    html_parts.append(
                        f"""<div style='border-left:5px solid {color};background:#F9FAFB;border-radius:6px;padding:8px 10px;'>
                        <div style='font-size:.68rem;color:#9CA3AF;'>{p['Pick']} · {p['Team']}</div>
                        <div style='font-weight:700;font-size:.85rem;color:#111827;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'>{p['Player']}</div>
                        <div style='font-size:.72rem;color:#6B7280;display:flex;justify-content:space-between;margin-top:2px;'>
                            <span>{p['Pos']} · {p['NFL Team']}</span><span>{badge}</span>
                        </div>
                        </div>"""
                    )
                html_parts.append("</div></div>")
            html_parts.append("</div>")
            st.markdown("".join(html_parts), unsafe_allow_html=True)

            st.markdown("---")
            st.subheader("Draft Value: Steals & Whiffs")
            st.caption(
                "Compares where a player was drafted against their CURRENT dynasty trade value from FantasyCalc. "
                "Went late but valuable now = steal. Went early but not worth much now = whiff. This is a snapshot, not a final verdict — values move."
            )
            dv_analysis = analytics.build_draft_value_analysis(draft_season)
            if dv_analysis.empty:
                st.caption("Dynasty values aren't available for this draft class right now (FantasyCalc data missing).")
            else:
                pos_colors_map = {"QB": "#DC2626", "RB": "#059669", "WR": "#1D4ED8", "TE": "#D97706"}
                scatter_fig = go.Figure()
                for pos, color in pos_colors_map.items():
                    sub = dv_analysis[dv_analysis["Pos"] == pos]
                    if sub.empty:
                        continue
                    scatter_fig.add_trace(
                        go.Scatter(
                            x=sub["Overall"], y=sub["Current Value"], mode="markers+text",
                            text=sub["Player"], textposition="top center", name=pos,
                            marker=dict(size=11, color=color),
                        )
                    )
                scatter_fig.update_layout(
                    xaxis_title="Draft pick (overall)", yaxis_title="Current dynasty value",
                    height=480, margin=dict(l=10, r=10, t=20, b=10),
                )
                st.plotly_chart(scatter_fig, width="stretch")

                steals = dv_analysis[dv_analysis["Tag"] == "🔥 Steal"].sort_values("Delta", ascending=False)
                whiffs = dv_analysis[dv_analysis["Tag"] == "❄️ Whiff"].sort_values("Delta")
                dv_c1, dv_c2 = st.columns(2)
                with dv_c1:
                    st.markdown("**🔥 Steals**")
                    if steals.empty:
                        st.caption("Nothing crossed the steal threshold yet.")
                    else:
                        st.dataframe(steals[["Pick", "Player", "Pos", "Team", "Current Value"]], width="stretch", hide_index=True)
                with dv_c2:
                    st.markdown("**❄️ Whiffs**")
                    if whiffs.empty:
                        st.caption("Nothing crossed the whiff threshold yet.")
                    else:
                        st.dataframe(whiffs[["Pick", "Player", "Pos", "Team", "Current Value"]], width="stretch", hide_index=True)

    st.caption("The 2024 startup draft isn't shown here - just the rookie drafts (2025 onward).")
