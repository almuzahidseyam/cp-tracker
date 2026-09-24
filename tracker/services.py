from django.core.cache import cache
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import re

def fetch_codeforces_data(handle):
    cache_key = f"cf_data_{handle}"
    cached_data = cache.get(cache_key)
    if cached_data: return cached_data

    url = f"https://codeforces.com/api/user.status?handle={handle}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'OK':
                submissions = data.get('result', [])
                solved_problems = set()
                
                for sub in submissions:
                    if sub.get('verdict') == 'OK':
                        prob = sub.get('problem', {})
                        prob_id = f"{prob.get('contestId')}{prob.get('index')}"
                        solved_problems.add(prob_id)
                        
                result = {
                    'total_solves': len(solved_problems),
                    'current_streak': 0, 
                    'max_streak': 0
                }
                cache.set(cache_key, result, 3600)
                return result
    except Exception as e:
        print(f"Error fetching CF data: {e}")
    return None

def fetch_codechef_data(handle):
    cache_key = f"cc_data_{handle}"
    cached_data = cache.get(cache_key)
    if cached_data: return cached_data

    url = f"https://www.codechef.com/users/{handle}"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            match = re.search(r"Total Problems Solved:\s*(\d+)", response.text)
            total_solves = int(match.group(1)) if match else 0
            
            result = {
                'total_solves': total_solves,
                'current_streak': 0,
                'max_streak': 0
            }
            cache.set(cache_key, result, 3600)
            return result
    except Exception as e:
        print(f"Error fetching CodeChef data: {e}")
    return None

def fetch_atcoder_data(handle):
    cache_key = f"ac_data_{handle}"
    cached_data = cache.get(cache_key)
    if cached_data: return cached_data

    url = f"https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?user={handle}&from_second=0"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            submissions = response.json()
            solved_problems = set()
            for sub in submissions:
                if sub.get('result') == 'AC':
                    solved_problems.add(sub.get('problem_id'))
                    
            result = {
                'total_solves': len(solved_problems),
                'current_streak': 0,
                'max_streak': 0
            }
            cache.set(cache_key, result, 3600)
            return result
    except Exception as e:
        print(f"Error fetching AtCoder data: {e}")
    return None

def fetch_leetcode_data(handle):
    cache_key = f"lc_data_{handle}"
    cached_data = cache.get(cache_key)
    if cached_data: return cached_data

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
    }
    """
    try:
        response = requests.post(url, json={'query': query, 'variables': {'username': handle}}, timeout=10)
        if response.status_code == 200:
            data = response.json()
            user_data = data.get('data', {}).get('matchedUser')
            if user_data:
                stats = user_data.get('submitStats', {}).get('acSubmissionNum', [])
                total_solves = 0
                for stat in stats:
                    if stat.get('difficulty') == 'All':
                        total_solves = stat.get('count', 0)
                        break
                
                result = {
                    'total_solves': total_solves,
                    'current_streak': 0,
                    'max_streak': 0
                }
                cache.set(cache_key, result, 3600)
                return result
    except Exception as e:
        print(f"Error fetching LeetCode data: {e}")
    return None

def update_user_handle_stats(user_handle):
    stats = None
    if user_handle.platform == 'CF':
        stats = fetch_codeforces_data(user_handle.handle)
    elif user_handle.platform == 'CC':
        stats = fetch_codechef_data(user_handle.handle)
    elif user_handle.platform == 'AC':
        stats = fetch_atcoder_data(user_handle.handle)
    elif user_handle.platform == 'LC':
        stats = fetch_leetcode_data(user_handle.handle)
        
    if stats:
        user_handle.total_solves = stats.get('total_solves', 0)
        user_handle.current_streak = stats.get('current_streak', 0)
        user_handle.max_streak = stats.get('max_streak', 0)
        user_handle.save()
        return True
    return False
