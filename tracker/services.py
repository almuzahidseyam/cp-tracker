from django.core.cache import cache
import requests
from datetime import datetime, timezone
import re
from .models import RecentSubmission, UserHandle
from django.db import transaction
from .authentication import reserve_cooldown


def fetch_codeforces_data(handle):
    cache_key = f"cf_data_{handle}"
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data

    url = "https://codeforces.com/api/user.status"
    try:
        response = requests.get(
            url, params={"handle": handle}, timeout=(3, 10), allow_redirects=False
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "OK":
                submissions = data.get("result", [])
                solved_problems = set()
                recent_subs = []

                # Sort submissions descending
                submissions.sort(
                    key=lambda x: x.get("creationTimeSeconds", 0), reverse=True
                )

                for sub in submissions:
                    if sub.get("verdict") == "OK":
                        prob = sub.get("problem", {})
                        prob_id = f"{prob.get('contestId')}{prob.get('index')}"

                        # Add to total solves set
                        solved_problems.add(prob_id)

                        # Add to recent subs (unique)
                        if len(recent_subs) < 15 and prob_id not in [
                            x["prob_id"] for x in recent_subs
                        ]:
                            recent_subs.append(
                                {
                                    "prob_id": prob_id,
                                    "problem_name": prob.get("name", prob_id),
                                    "problem_url": f"https://codeforces.com/contest/{prob.get('contestId')}/problem/{prob.get('index')}",
                                    "timestamp": sub.get("creationTimeSeconds", 0),
                                }
                            )

                # Fetch Rating and Rank from user.info API
                rating = 0
                max_rating = 0
                rank = "Unrated"
                max_rank = "Unrated"
                try:
                    info_url = "https://codeforces.com/api/user.info"
                    info_res = requests.get(
                        info_url,
                        params={"handles": handle},
                        timeout=(3, 5),
                        allow_redirects=False,
                    )
                    if info_res.status_code == 200:
                        info_data = info_res.json()
                        if (
                            info_data.get("status") == "OK"
                            and len(info_data.get("result", [])) > 0
                        ):
                            user_info = info_data["result"][0]
                            rating = user_info.get("rating", 0)
                            max_rating = user_info.get("maxRating", 0)
                            rank = user_info.get("rank", "Unrated").title()
                            max_rank = user_info.get("maxRank", "Unrated").title()
                except Exception as ex:
                    print(f"Error fetching CF user info: {ex}")

                result = {
                    "total_solves": len(solved_problems),
                    "rating": rating,
                    "max_rating": max_rating,
                    "rank": rank,
                    "max_rank": max_rank,
                    "current_streak": 0,
                    "max_streak": 0,
                    "recent_submissions": recent_subs,
                }
                cache.set(cache_key, result, 3600)
                return result
    except Exception as e:
        print(f"Error fetching CF data: {e}")
    return None


def fetch_codechef_data(handle):
    cache_key = f"cc_data_{handle}"
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data

    url = f"https://www.codechef.com/users/{handle}"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(
            url, headers=headers, timeout=(3, 10), allow_redirects=False
        )
        if response.status_code == 200:
            match = re.search(r"Total Problems Solved:\s*(\d+)", response.text)
            if not match:
                return None
            total_solves = int(match.group(1))

            result = {
                "total_solves": total_solves,
                "current_streak": 0,
                "max_streak": 0,
                "recent_submissions": [],
            }
            cache.set(cache_key, result, 3600)
            return result
    except Exception as e:
        print(f"Error fetching CodeChef data: {e}")
    return None


def fetch_atcoder_data(handle):
    cache_key = f"ac_data_{handle}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    # Aggregate count avoids treating a paginated submissions slice as the lifetime total.
    if not reserve_cooldown("atcoder-api", 1.1):
        return None
    try:
        profile = requests.get(
            "https://atcoder.jp/users/" + handle, timeout=(3, 10), allow_redirects=False
        )
        if profile.status_code != 200:
            return None
        response = requests.get(
            "https://kenkoooo.com/atcoder/atcoder-api/v3/user/ac_rank",
            params={"user": handle},
            timeout=(3, 10),
            allow_redirects=False,
        )
        response.raise_for_status()
        data = response.json()
        count = data.get("count")
        if type(count) is not int or count < 0:
            return None
        result = {
            "total_solves": count,
            "current_streak": 0,
            "max_streak": 0,
            "recent_submissions": [],
        }
        cache.set(cache_key, result, 3600)
        return result
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return None


def fetch_leetcode_data(handle):
    cache_key = f"lc_data_{handle}"
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data

    url = "https://leetcode.com/graphql"
    query = """
    query getUserProfile($username: String!) {
      matchedUser(username: $username) {
        submitStats {
          acSubmissionNum {
            difficulty
            count
          }
        }
      }
      userContestRanking(username: $username) {
        rating
        badge {
          name
        }
      }
      recentAcSubmissionList(username: $username, limit: 15) {
        title
        titleSlug
        timestamp
      }
    }
    """
    try:
        response = requests.post(
            url,
            json={"query": query, "variables": {"username": handle}},
            timeout=(3, 10),
            allow_redirects=False,
        )
        if response.status_code == 200:
            data = response.json()
            user_data = data.get("data", {}).get("matchedUser")
            if not user_data:
                return None
            total_solves = 0
            recent_subs = []

            if user_data:
                stats = user_data.get("submitStats", {}).get("acSubmissionNum", [])
                for stat in stats:
                    if stat.get("difficulty") == "All":
                        total_solves = stat.get("count", 0)
                        break

            rating = 0
            rank = "Unrated"
            contest_data = data.get("data", {}).get("userContestRanking")
            if contest_data:
                rating = int(contest_data.get("rating", 0))
                badge = contest_data.get("badge")
                if badge:
                    rank = badge.get("name", "Unrated")

            recent_ac = data.get("data", {}).get("recentAcSubmissionList", [])
            if recent_ac:
                for sub in recent_ac:
                    recent_subs.append(
                        {
                            "prob_id": sub.get("titleSlug"),
                            "problem_name": sub.get("title"),
                            "problem_url": f"https://leetcode.com/problems/{sub.get('titleSlug')}/",
                            "timestamp": int(sub.get("timestamp", 0)),
                        }
                    )

            result = {
                "total_solves": total_solves,
                "rating": rating,
                "rank": rank,
                "current_streak": 0,
                "max_streak": 0,
                "recent_submissions": recent_subs,
            }
            cache.set(cache_key, result, 3600)
            return result
    except Exception as e:
        print(f"Error fetching LeetCode data: {e}")
    return None


def fetch_handle_stats(platform, handle):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,50}", handle):
        return None
    fetcher = {
        "CF": fetch_codeforces_data,
        "CC": fetch_codechef_data,
        "AC": fetch_atcoder_data,
        "LC": fetch_leetcode_data,
    }.get(platform)
    if not fetcher:
        return None
    stats = fetcher(handle)
    if (
        not isinstance(stats, dict)
        or type(stats.get("total_solves")) is not int
        or stats["total_solves"] < 0
    ):
        return None
    try:
        recent = stats.get("recent_submissions", [])[:15]
        for sub in recent:
            datetime.fromtimestamp(sub["timestamp"], tz=timezone.utc)
            if (
                not isinstance(sub["problem_name"], str)
                or len(sub["problem_name"]) > 255
                or not isinstance(sub["problem_url"], str)
                or len(sub["problem_url"]) > 500
            ):
                return None
        if stats.get("rating") is not None and type(stats["rating"]) is not int:
            return None
    except (ValueError, TypeError, KeyError, OverflowError, OSError):
        return None
    return stats


def apply_handle_stats(user_handle, stats):
    user_handle.total_solves = stats["total_solves"]
    user_handle.current_streak = stats.get("current_streak", 0)
    user_handle.max_streak = stats.get("max_streak", 0)
    user_handle.rating = stats.get("rating")
    user_handle.rank = str(stats.get("rank", ""))[:100]
    user_handle.save()
    # Clear old account history even when the newly validated account has no recent solves.
    RecentSubmission.objects.filter(handle=user_handle).delete()
    RecentSubmission.objects.bulk_create(
        [
            RecentSubmission(
                handle=user_handle,
                problem_name=sub["problem_name"],
                problem_url=sub["problem_url"],
                timestamp=datetime.fromtimestamp(sub["timestamp"], tz=timezone.utc),
            )
            for sub in stats.get("recent_submissions", [])[:15]
        ]
    )


def update_user_handle_stats(user_handle):
    stats = fetch_handle_stats(user_handle.platform, user_handle.handle)
    if stats is None:
        return False
    with transaction.atomic():
        current = (
            UserHandle.objects.select_for_update()
            .filter(
                pk=user_handle.pk,
                handle=user_handle.handle,
                platform=user_handle.platform,
                user_id=user_handle.user_id,
            )
            .first()
        )
        if current is None:
            return False  # Never undo a concurrent edit or resurrect a deleted handle.
        apply_handle_stats(current, stats)
    return True
