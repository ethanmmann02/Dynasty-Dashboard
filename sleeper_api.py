"""
Sleeper API wrapper - Nicos Dynasty League
--------------------------------------------
Handles all calls to the public Sleeper API, with caching.

Dynasty leagues chain seasons via previous_league_id, but rather than
trust that chain blindly we pin the known league_id per season since
Ethan already has them. get_league_chain() still walks previous_league_id
as a fallback for any season not in the hardcoded map.
"""

import time

import requests
import streamlit as st

BASE = "https://api.sleeper.app/v1"

SEASON_LEAGUE_IDS = {
    2026: "1312479635501514752",
    2025: "1180194758214021120",
    2024: "1126013684108668928",
}
CURRENT_SEASON = max(SEASON_LEAGUE_IDS)
CURRENT_LEAGUE_ID = SEASON_LEAGUE_IDS[CURRENT_SEASON]
ALL_SEASONS = sorted(SEASON_LEAGUE_IDS.keys())


def _get(url: str, timeout: int = 15, retries: int = 3):
    """
    GET with retry/backoff - Sleeper's API occasionally times out or
    hiccups under load, and without this a single slow response used
    to crash the whole app. Retries on timeout/connection errors and
    5xx server errors; does NOT retry on 4xx (bad league id, etc),
    since retrying a request that's wrong won't fix it.
    """
    last_exc = None
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code >= 500:
                raise requests.exceptions.HTTPError(f"{r.status_code} server error")
            r.raise_for_status()
            return r.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.HTTPError) as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))  # 1.5s, 3s backoff
            continue
    raise last_exc


@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_league(league_id: str) -> dict:
    return _get(f"{BASE}/league/{league_id}")


@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_rosters(league_id: str) -> list:
    return _get(f"{BASE}/league/{league_id}/rosters")


@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_users(league_id: str) -> list:
    return _get(f"{BASE}/league/{league_id}/users")


@st.cache_data(ttl=60 * 15, show_spinner=False)
def get_matchups(league_id: str, week: int) -> list:
    return _get(f"{BASE}/league/{league_id}/matchups/{week}")


@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_winners_bracket(league_id: str) -> list:
    return _get(f"{BASE}/league/{league_id}/winners_bracket")


@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_losers_bracket(league_id: str) -> list:
    return _get(f"{BASE}/league/{league_id}/losers_bracket")


@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_transactions(league_id: str, round_: int) -> list:
    return _get(f"{BASE}/league/{league_id}/transactions/{round_}")


@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_traded_picks(league_id: str) -> list:
    """All traded picks in this league (past and future) - each entry has season, round,
    roster_id (ORIGINAL owner), previous_owner_id, and owner_id (CURRENT/final owner).
    Lets us resolve a pick through multiple re-trades to whoever actually held it on draft day."""
    return _get(f"{BASE}/league/{league_id}/traded_picks")


@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_drafts(league_id: str) -> list:
    return _get(f"{BASE}/league/{league_id}/drafts")


@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_draft_picks(draft_id: str) -> list:
    return _get(f"{BASE}/draft/{draft_id}/picks")


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def get_all_players() -> dict:
    """
    Full NFL player dictionary keyed by player_id (~5MB). Cached hard
    for 24h, Sleeper asks devs to only call this once per day per app.
    """
    return _get(f"{BASE}/players/nfl", timeout=30)


@st.cache_data(ttl=60 * 30, show_spinner=False)
def get_league_chain(league_id: str) -> list:
    """
    Fallback walk backwards through previous_league_id. Prefer
    SEASON_LEAGUE_IDS above when the season is known.
    """
    chain = []
    current_id = league_id
    seen = set()
    while current_id and current_id not in seen:
        seen.add(current_id)
        league = get_league(current_id)
        chain.append(league)
        current_id = league.get("previous_league_id")
    return list(reversed(chain))


def build_owner_map(users: list, rosters: list) -> dict:
    """roster_id -> manager's real Sleeper display name. Never the team name."""
    user_by_id = {u["user_id"]: u for u in users}
    owner_map = {}
    for roster in rosters:
        owner_id = roster.get("owner_id")
        user = user_by_id.get(owner_id, {})
        owner_map[roster["roster_id"]] = user.get("display_name", "Unknown")
    return owner_map


def build_owner_id_map(users: list, rosters: list) -> dict:
    """
    roster_id -> owner_id (the stable Sleeper user id). Needed to link
    a manager across seasons, since roster_id resets each year but
    owner_id doesn't (assuming same person keeps the team).
    """
    return {r["roster_id"]: r.get("owner_id") for r in rosters}


def build_display_name_map(users: list) -> dict:
    """owner_id -> Sleeper display_name (the manager's actual name, not team name)."""
    return {u["user_id"]: u.get("display_name", "Unknown") for u in users}
