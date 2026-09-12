#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path


# =============================================================================
# PATHS
# =============================================================================

ROOT = Path(__file__).resolve().parents[1]

ASSETS = ROOT / "assets"
CONFIG = ROOT / "config" / "profile.toml"


# =============================================================================
# COLORS / STYLE
# =============================================================================

BG = "#050505"
PANEL = "#080808"
BORDER = "#2A0B14"

RED_DARK = "#8A0F2C"
RED = "#C1123F"

TEXT = "#F2F2F2"
MUTED = "#909090"
FAINT = "#5A5A5A"

GRID0 = "#120609"
GRID1 = "#310A14"
GRID2 = "#650D22"
GRID3 = "#A31034"
GRID4 = "#F01D49"

FONT = (
    "ui-monospace, SFMono-Regular, Menlo, Monaco, "
    "Consolas, monospace"
)


# =============================================================================
# HELPERS
# =============================================================================

def esc(value) -> str:
    return html.escape(
        str(value),
        quote=True,
    )


def load_config() -> dict:
    with CONFIG.open("rb") as file:
        return tomllib.load(file)


def fmt(value) -> str:
    """
    GitHub dashboard number formatting.

    8468 -> 8.468
    12500 -> 12.5K
    """
    if value is None:
        return "—"

    value = int(value)

    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"

    if value >= 10_000:
        return f"{value / 1_000:.1f}K"

    return f"{value:,}".replace(",", ".")


def parse_github_datetime(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )


# =============================================================================
# GITHUB GRAPHQL
# =============================================================================

def graphql(
    token: str,
    login: str,
) -> dict:
    """
    Important:

    We DO NOT manually specify `from` / `to`.

    GitHub therefore uses the same default contribution window that it uses
    for contributionsCollection itself.

    This prevents our dashboard from being one day short compared with the
    GitHub profile total.
    """

    query = r"""
    query($login: String!) {
      user(login: $login) {

        repositories(
          first: 1
          ownerAffiliations: OWNER
        ) {
          totalCount
        }

        contributionsCollection {

          startedAt
          endedAt

          contributionCalendar {

            totalContributions

            weeks {
              contributionDays {
                contributionCount
                date
                weekday
              }
            }
          }

          totalCommitContributions
          totalIssueContributions
          totalPullRequestContributions
          totalPullRequestReviewContributions
          restrictedContributionsCount
        }
      }
    }
    """

    body = json.dumps(
        {
            "query": query,
            "variables": {
                "login": login,
            },
        }
    ).encode()

    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "01xor-profile-dashboard",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            payload = json.loads(
                response.read().decode()
            )

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(
            errors="replace"
        )

        raise RuntimeError(
            f"GitHub GraphQL HTTP {exc.code}: "
            f"{detail[:1000]}"
        ) from exc

    if payload.get("errors"):
        raise RuntimeError(
            "GitHub GraphQL error: "
            + json.dumps(
                payload["errors"]
            )[:1500]
        )

    user = (
        payload
        .get("data", {})
        .get("user")
    )

    if not user:
        raise RuntimeError(
            f"GitHub user not found: {login}"
        )

    return user


# =============================================================================
# CONTRIBUTION ANALYSIS
# =============================================================================

def calc_streaks(
    days: list[dict],
) -> tuple[int, int, int]:
    """
    Returns:

    active_days
    current_streak
    longest_streak
    """

    by_date: dict[
        dt.date,
        int
    ] = {}

    for item in days:

        try:
            date = dt.date.fromisoformat(
                item["date"]
            )

            count = int(
                item["contributionCount"]
            )

            by_date[date] = count

        except Exception:
            continue

    if not by_date:
        return 0, 0, 0

    dates = sorted(
        by_date
    )

    active_days = sum(
        1
        for value in by_date.values()
        if value > 0
    )

    # -------------------------------------------------------------------------
    # LONGEST STREAK
    # -------------------------------------------------------------------------

    longest = 0
    run = 0

    for day in dates:

        if by_date[day] > 0:

            previous = (
                day
                - dt.timedelta(days=1)
            )

            if by_date.get(
                previous,
                0,
            ) > 0:
                run += 1

            else:
                run = 1

            longest = max(
                longest,
                run,
            )

        else:
            run = 0

    # -------------------------------------------------------------------------
    # CURRENT STREAK
    # -------------------------------------------------------------------------

    today = (
        dt.datetime
        .now(
            dt.timezone.utc
        )
        .date()
    )

    cursor = today

    # If today has no contribution yet,
    # count backwards starting yesterday.
    if by_date.get(
        cursor,
        0,
    ) == 0:

        cursor -= dt.timedelta(
            days=1
        )

    current = 0

    while by_date.get(
        cursor,
        0,
    ) > 0:

        current += 1

        cursor -= dt.timedelta(
            days=1
        )

    return (
        active_days,
        current,
        longest,
    )


# =============================================================================
# OFFLINE PLACEHOLDER
# =============================================================================

def placeholder_metrics() -> dict:
    """
    Used by:

        python scripts/generate_dashboard.py --offline

    It creates a valid SVG without contacting GitHub.
    """

    today = (
        dt.datetime
        .now(
            dt.timezone.utc
        )
        .date()
    )

    start = (
        today
        - dt.timedelta(
            days=365
        )
    )

    days = []

    cursor = start

    while cursor <= today:

        days.append(
            {
                "date": cursor.isoformat(),
                "contributionCount": 0,
                "weekday": cursor.weekday(),
            }
        )

        cursor += dt.timedelta(
            days=1
        )

    return {
        "total": None,
        "commits": None,
        "prs": None,
        "issues": None,
        "reviews": None,
        "repos": None,
        "private": None,

        "days": days,

        "active_days": None,
        "current_streak": None,
        "longest_streak": None,

        "from": start.isoformat(),
        "to": today.isoformat(),

        "synced": "SYNC PENDING",

        "token_mode": (
            "PUBLIC / PLACEHOLDER"
        ),
    }


# =============================================================================
# COLLECT GITHUB METRICS
# =============================================================================

def collect_metrics(
    cfg: dict,
    offline: bool = False,
) -> dict:

    if offline:
        return placeholder_metrics()

    token = (
        os.getenv("PROFILE_TOKEN")
        or os.getenv("GITHUB_TOKEN")
        or os.getenv("GH_TOKEN")
    )

    if not token:

        print(
            (
                "No GitHub token available. "
                "Rendering placeholder metrics."
            ),
            file=sys.stderr,
        )

        return placeholder_metrics()

    login = cfg["profile"]["login"]

    now = dt.datetime.now(
        dt.timezone.utc
    )

    user = graphql(
        token,
        login,
    )

    cc = user[
        "contributionsCollection"
    ]

    calendar = cc[
        "contributionCalendar"
    ]

    # -------------------------------------------------------------------------
    # USE GITHUB'S ACTUAL WINDOW
    # -------------------------------------------------------------------------

    started_at = parse_github_datetime(
        cc["startedAt"]
    )

    ended_at = parse_github_datetime(
        cc["endedAt"]
    )

    start_date = started_at.date()
    end_date = ended_at.date()

    # -------------------------------------------------------------------------
    # FLATTEN CONTRIBUTION CALENDAR
    # -------------------------------------------------------------------------

    all_days = [
        day

        for week
        in calendar["weeks"]

        for day
        in week["contributionDays"]
    ]

    # contributionCalendar is week-based and can contain days just outside
    # the exact contributionCollection range.
    #
    # Filter using GitHub's own startedAt / endedAt.
    days = [
        day

        for day in all_days

        if (
            start_date
            <= dt.date.fromisoformat(
                day["date"]
            )
            <= end_date
        )
    ]

    (
        active_days,
        current_streak,
        longest_streak,

    ) = calc_streaks(
        days
    )

    return {

        # ---------------------------------------------------------------------
        # HEADLINE NUMBER
        # ---------------------------------------------------------------------

        "total":
            calendar[
                "totalContributions"
            ],

        # ---------------------------------------------------------------------
        # DETAILS
        # ---------------------------------------------------------------------

        "commits":
            cc[
                "totalCommitContributions"
            ],

        "prs":
            cc[
                "totalPullRequestContributions"
            ],

        "issues":
            cc[
                "totalIssueContributions"
            ],

        "reviews":
            cc[
                "totalPullRequestReviewContributions"
            ],

        "repos":
            user[
                "repositories"
            ][
                "totalCount"
            ],

        "private":
            cc.get(
                "restrictedContributionsCount",
                0,
            ),

        "days":
            days,

        "active_days":
            active_days,

        "current_streak":
            current_streak,

        "longest_streak":
            longest_streak,

        # ---------------------------------------------------------------------
        # EXACT GITHUB WINDOW
        # ---------------------------------------------------------------------

        "from":
            start_date.isoformat(),

        "to":
            end_date.isoformat(),

        "synced":
            now.strftime(
                "%Y-%m-%d %H:%M UTC"
            ),

        "token_mode":
            (
                "PROFILE TOKEN"

                if os.getenv(
                    "PROFILE_TOKEN"
                )

                else "GITHUB_TOKEN"
            ),
    }


# =============================================================================
# CONTRIBUTION MATRIX COLORS
# =============================================================================

def level_color(
    count: int,
    max_count: int,
) -> str:

    if count <= 0:
        return GRID0

    if max_count <= 1:
        return GRID4

    ratio = (
        count
        / max_count
    )

    if ratio <= 0.18:
        return GRID1

    if ratio <= 0.40:
        return GRID2

    if ratio <= 0.68:
        return GRID3

    return GRID4


# =============================================================================
# SVG DASHBOARD
# =============================================================================

def render_dashboard(
    cfg: dict,
    m: dict,
) -> str:

    focus = cfg.get(
        "focus",
        [],
    )[:6]

    signals = cfg.get(
        "signals",
        [],
    )[:5]

    width = 1200
    height = 1565

    out: list[str] = []

    a = out.append

    # =========================================================================
    # BASE SVG
    # =========================================================================

    a(
        f'''
<svg
  width="{width}"
  height="{height}"
  viewBox="0 0 {width} {height}"
  fill="none"
  xmlns="http://www.w3.org/2000/svg"
  role="img"
  aria-label="01xor profile dashboard"
>

<defs>

  <filter
    id="glow"
    x="-30%"
    y="-80%"
    width="160%"
    height="260%"
  >
    <feGaussianBlur
      stdDeviation="2.4"
      result="b"
    />

    <feMerge>
      <feMergeNode in="b"/>
      <feMergeNode in="SourceGraphic"/>
    </feMerge>
  </filter>


  <pattern
    id="grid"
    width="40"
    height="40"
    patternUnits="userSpaceOnUse"
  >
    <path
      d="M40 0H0V40"
      fill="none"
      stroke="#14070A"
      stroke-width="1"
    />
  </pattern>


  <linearGradient
    id="line"
    x1="0"
    y1="0"
    x2="1"
    y2="0"
  >
    <stop
      offset="0%"
      stop-color="{RED_DARK}"
      stop-opacity="0"
    />

    <stop
      offset="16%"
      stop-color="{RED_DARK}"
      stop-opacity=".9"
    />

    <stop
      offset="55%"
      stop-color="{RED}"
    />

    <stop
      offset="100%"
      stop-color="{RED_DARK}"
      stop-opacity="0"
    />
  </linearGradient>


  <linearGradient
    id="scan"
    x1="0"
    y1="0"
    x2="0"
    y2="1"
  >
    <stop
      offset="0%"
      stop-color="{RED}"
      stop-opacity="0"
    />

    <stop
      offset="50%"
      stop-color="{RED}"
      stop-opacity=".08"
    />

    <stop
      offset="100%"
      stop-color="{RED}"
      stop-opacity="0"
    />
  </linearGradient>

</defs>


<rect
  width="{width}"
  height="{height}"
  fill="{BG}"
/>

<rect
  width="{width}"
  height="{height}"
  fill="url(#grid)"
/>

<rect
  x="20"
  y="20"
  width="1160"
  height="1525"
  rx="10"
  fill="{PANEL}"
  stroke="{BORDER}"
  stroke-width="1.5"
/>


<rect
  x="20"
  y="-30"
  width="1160"
  height="30"
  fill="url(#scan)"
>
  <animate
    attributeName="y"
    values="-30;1565;-30"
    dur="16s"
    repeatCount="indefinite"
  />
</rect>


<g
  stroke="{RED_DARK}"
  stroke-width="3"
  filter="url(#glow)"
>

  <path
    d="M36 36H88M36 36V88"
  />

  <path
    d="M1164 36H1112M1164 36V88"
  />

  <path
    d="M36 1529H88M36 1529V1477"
  />

  <path
    d="M1164 1529H1112M1164 1529V1477"
  />

</g>
'''
    )

    # =========================================================================
    # HERO
    # =========================================================================

    a(
        f'''
<g
  font-family="{FONT}"
  font-size="18"
  fill="#8B8B8B"
  letter-spacing="1.3"
>

  <text
    x="50"
    y="60"
  >NODE :: 01XOR</text>

  <text
    x="50"
    y="86"
  >MODE :: BUILD / LEARN</text>

</g>


<g
  font-family="{FONT}"
  font-size="18"
  fill="#8B8B8B"
  text-anchor="end"
  letter-spacing="1.3"
>

  <text
    x="1148"
    y="60"
  >CS + MATH</text>

  <text
    x="1148"
    y="86"
  >STATUS :: ONLINE</text>

</g>


<text
  x="600"
  y="150"
  text-anchor="middle"
  font-family="{FONT}"
  font-size="108"
  font-weight="800"
  letter-spacing="7"
  fill="{TEXT}"
  filter="url(#glow)"
>01xor</text>


<text
  x="600"
  y="198"
  text-anchor="middle"
  font-family="{FONT}"
  font-size="29"
  font-weight="700"
  letter-spacing="4"
  fill="{RED}"
>SECURITY // BLOCKCHAIN // SYSTEMS</text>


<rect
  x="205"
  y="220"
  width="790"
  height="3"
  rx="1.5"
  fill="url(#line)"
  filter="url(#glow)"
/>
'''
    )

    # =========================================================================
    # 01 // ACTIVITY
    # =========================================================================

    y = 285

    a(
        f'''
<text
  x="55"
  y="{y}"
  font-family="{FONT}"
  font-size="23"
  font-weight="700"
  letter-spacing="2.2"
  fill="{RED}"
>01</text>


<text
  x="110"
  y="{y}"
  font-family="{FONT}"
  font-size="33"
  font-weight="700"
  letter-spacing="1.2"
  fill="{TEXT}"
>// ACTIVITY</text>


<text
  x="1145"
  y="{y}"
  text-anchor="end"
  font-family="{FONT}"
  font-size="17"
  letter-spacing="1.1"
  fill="#90909000"
>LAST SYNC :: {esc(m["synced"])}</text>


<rect
  x="55"
  y="{y + 19}"
  width="1090"
  height="2"
  rx="1"
  fill="url(#line)"
/>
'''
    )

    # Main total
    a(
        f'''
<text
  x="70"
  y="{y + 136}"
  font-family="{FONT}"
  font-size="138"
  font-weight="800"
  fill="{TEXT}"
  filter="url(#glow)"
>{fmt(m["total"])}</text>


<text
  x="42"
  y="{y + 186}"
  font-family="{FONT}"
  font-size="23"
  font-weight="700"
  letter-spacing="1"
  fill="{RED}"
>CONTRIBUTIONS / LAST 365 DAYS</text>
'''
    )

    # -------------------------------------------------------------------------
    # Activity stats
    # -------------------------------------------------------------------------

    stats = [
        (
            "COMMITS",
            fmt(
                m["commits"]
            ),
            TEXT,
        ),
        (
            "ACTIVE DAYS",
            fmt(
                m["active_days"]
            ),
            TEXT,
        ),
        (
            "OWN REPOS",
            fmt(
                m["repos"]
            ),
            TEXT,
        ),
        (
            "PULL REQUESTS",
            fmt(
                m["prs"]
            ),
            TEXT,
        ),
        (
            "CURRENT STREAK",
            f'{fmt(m["current_streak"])} DAYS',
            RED,
        ),
        (
            "LONGEST STREAK",
            f'{fmt(m["longest_streak"])} DAYS',
            RED,
        ),
    ]

    stat_x = [
        470,
        700,
        930,
    ]

    for index, (
        label,
        value,
        color,

    ) in enumerate(stats):

        row = index // 3
        col = index % 3

        x = stat_x[col]

        top_y = (
            y
            + 92
            + row * 104
        )

        if col > 0:

            a(
                f'''
<line
  x1="{x - 36}"
  y1="{top_y - 36}"
  x2="{x - 36}"
  y2="{top_y + 36}"
  stroke="#241018"
/>
'''
            )

        a(
            f'''
<text
  x="{x}"
  y="{top_y}"
  font-family="{FONT}"
  font-size="17"
  letter-spacing="1.2"
  fill="{MUTED}"
>{esc(label)}</text>


<text
  x="{x}"
  y="{top_y + 46}"
  font-family="{FONT}"
  font-size="42"
  font-weight="700"
  fill="{color}"
>{esc(value)}</text>
'''
        )

    # =========================================================================
    # 02 // CONTRIBUTION MATRIX
    # =========================================================================

    y = 585

    a(
        f'''
<text
  x="55"
  y="{y}"
  font-family="{FONT}"
  font-size="23"
  font-weight="700"
  letter-spacing="2.2"
  fill="{RED}"
>02</text>


<text
  x="110"
  y="{y}"
  font-family="{FONT}"
  font-size="33"
  font-weight="700"
  letter-spacing="1.2"
  fill="{TEXT}"
>// CONTRIBUTION MATRIX</text>


<text
  x="1145"
  y="{y}"
  text-anchor="end"
  font-family="{FONT}"
  font-size="17"
  letter-spacing="1.1"
  fill="{MUTED}"
>{esc(m["from"])} → {esc(m["to"])}</text>


<rect
  x="55"
  y="{y + 19}"
  width="1090"
  height="2"
  rx="1"
  fill="url(#line)"
/>
'''
    )

    parsed = [
        (
            dt.date.fromisoformat(
                day["date"]
            ),
            int(
                day["contributionCount"]
            ),
        )

        for day
        in m["days"]
    ]

    if parsed:

        max_count = max(
            (
                count

                for _,
                count
                in parsed
            ),
            default=0,
        )

        by_date = dict(
            parsed
        )

        start = parsed[0][0]

        sunday_index = (
            start.weekday()
            + 1
        ) % 7

        grid_start = (
            start
            - dt.timedelta(
                days=sunday_index
            )
        )

        cell = 15
        step = 19

        x0 = 112
        grid_y = 651

        cursor = grid_start

        end = parsed[-1][0]

        while cursor <= end:

            if cursor >= start:

                week = (
                    cursor
                    - grid_start
                ).days // 7

                row = (
                    cursor.weekday()
                    + 1
                ) % 7

                x = (
                    x0
                    + week * step
                )

                cell_y = (
                    grid_y
                    + row * step
                )

                count = by_date.get(
                    cursor,
                    0,
                )

                color = level_color(
                    count,
                    max_count,
                )

                a(
                    f'''
<rect
  x="{x}"
  y="{cell_y}"
  width="{cell}"
  height="{cell}"
  rx="2"
  fill="{color}"
/>
'''
                )

            cursor += dt.timedelta(
                days=1
            )

        # Weekday labels
        for label, row in [
            ("M", 1),
            ("W", 3),
            ("F", 5),
        ]:

            label_y = (
                grid_y
                + row * step
                + 13
            )

            a(
                f'''
<text
  x="78"
  y="{label_y}"
  font-family="{FONT}"
  font-size="15"
  fill="{FAINT}"
>{label}</text>
'''
            )

        # Legend
        legend_y = (
            grid_y
            + 146
        )

        a(
            f'''
<text
  x="112"
  y="{legend_y + 14}"
  font-family="{FONT}"
  font-size="15"
  fill="{MUTED}"
>less</text>
'''
        )

        legend_x = 154

        colors = [
            GRID0,
            GRID1,
            GRID2,
            GRID3,
            GRID4,
        ]

        for index, color in enumerate(
            colors
        ):

            a(
                f'''
<rect
  x="{legend_x + index * 19}"
  y="{legend_y}"
  width="13"
  height="13"
  rx="2"
  fill="{color}"
/>
'''
            )

        a(
            f'''
<text
  x="{legend_x + 112}"
  y="{legend_y + 14}"
  font-family="{FONT}"
  font-size="15"
  fill="{MUTED}"
>more</text>
'''
        )

    # =========================================================================
    # 03 // FOCUS
    # =========================================================================

    y = 875

    a(
        f'''
<text
  x="55"
  y="{y}"
  font-family="{FONT}"
  font-size="23"
  font-weight="700"
  letter-spacing="2.2"
  fill="{RED}"
>03</text>


<text
  x="110"
  y="{y}"
  font-family="{FONT}"
  font-size="33"
  font-weight="700"
  letter-spacing="1.2"
  fill="{TEXT}"
>// FOCUS</text>


<rect
  x="55"
  y="{y + 19}"
  width="1090"
  height="2"
  rx="1"
  fill="url(#line)"
/>
'''
    )

    for index, item in enumerate(
        focus
    ):

        item_y = (
            y
            + 72
            + index * 47
        )

        a(
            f'''
<text
  x="70"
  y="{item_y}"
  font-family="{FONT}"
  font-size="20"
  font-weight="700"
  fill="{RED}"
>{esc(item["name"])}</text>


<text
  x="290"
  y="{item_y}"
  font-family="{FONT}"
  font-size="19"
  fill="{TEXT}"
>{esc(item["description"])}</text>
'''
        )

    # =========================================================================
    # 04 // FIND ME
    # =========================================================================

    y = 1260

    a(
        f'''
<text
  x="55"
  y="{y}"
  font-family="{FONT}"
  font-size="23"
  font-weight="700"
  letter-spacing="2.2"
  fill="{RED}"
>04</text>


<text
  x="110"
  y="{y}"
  font-family="{FONT}"
  font-size="33"
  font-weight="700"
  letter-spacing="1.2"
  fill="{TEXT}"
>// FIND ME</text>


<text
  x="1145"
  y="{y}"
  text-anchor="end"
  font-family="{FONT}"
  font-size="17"
  letter-spacing="1.1"
  fill="{MUTED}"
>NETWORK / LINKS</text>


<rect
  x="55"
  y="{y + 19}"
  width="1090"
  height="2"
  rx="1"
  fill="url(#line)"
/>
'''
    )

    for index, item in enumerate(
        signals
    ):

        item_y = (
            y
            + 72
            + index * 46
        )

        a(
            f'''
<circle
  cx="76"
  cy="{item_y - 7}"
  r="4.5"
  fill="{RED}"
  filter="url(#glow)"
>
  <animate
    attributeName="opacity"
    values=".35;1;.35"
    dur="2.2s"
    begin="{index * 0.2}s"
    repeatCount="indefinite"
  />
</circle>


<text
  x="98"
  y="{item_y}"
  font-family="{FONT}"
  font-size="18"
  font-weight="700"
  fill="{RED}"
>{esc(item["platform"])}</text>


<text
  x="300"
  y="{item_y}"
  font-family="{FONT}"
  font-size="22"
  font-weight="700"
  fill="{TEXT}"
>{esc(item["handle"])}</text>


<text
  x="1130"
  y="{item_y}"
  text-anchor="end"
  font-family="{FONT}"
  font-size="17"
  fill="{MUTED}"
>{esc(item["status"])}</text>
'''
        )

    # =========================================================================
    # FOOTER
    # =========================================================================

    a(
        f'''
<text
  x="600"
  y="1495"
  text-anchor="middle"
  font-family="{FONT}"
  font-size="22"
  fill="{TEXT}"
>0x01 :: EOF</text>


</svg>
'''
    )

    return "".join(
        out
    )


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Generate the 01xor "
            "GitHub profile dashboard."
        )
    )

    parser.add_argument(
        "--offline",
        action="store_true",
        help=(
            "Generate placeholder SVG "
            "without contacting GitHub."
        ),
    )

    args = parser.parse_args()

    cfg = load_config()

    metrics = collect_metrics(
        cfg,
        offline=args.offline,
    )

    svg = render_dashboard(
        cfg,
        metrics,
    )

    ASSETS.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = (
        ASSETS
        / "dashboard.svg"
    )

    output.write_text(
        svg,
        encoding="utf-8",
    )

    print(
        f"Generated {output}"
    )

    if not args.offline:

        print(
            "GitHub contribution window:"
        )

        print(
            f'  {metrics["from"]}'
            f' -> '
            f'{metrics["to"]}'
        )

        print(
            "Total contributions:"
        )

        print(
            f'  {metrics["total"]}'
        )


if __name__ == "__main__":
    main()