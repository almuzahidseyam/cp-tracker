from django.core.cache import cache
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import re
from .models import RecentSubmission

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
                recent_subs = []
                
                # Sort submissions descending
                submissions.sort(key=lambda x: x.get('creationTimeSeconds', 0), reverse=True)
                
                for sub in submissions:
                    if sub.get('verdict') == 'OK':
                        prob = sub.get('problem', {})
                        prob_id = f"{prob.get('contestId')}{prob.get('index')}"
                        
                        # Add to total solves set
                        solved_problems.add(prob_id)
                        
                        # Add to recent subs (unique)
                        if len(recent_subs) < 15 and prob_id not in [x['prob_id'] for x in recent_subs]:
                            recent_subs.append({
                                'prob_id': prob_id,
                                'problem_name': prob.get('name', prob_id),
                                'problem_url': f"https://codeforces.com/contest/{prob.get('contestId')}/problem/{prob.get('index')}",
                                'timestamp': sub.get('creationTimeSeconds', 0)
                            })
                        
                result = {
                    'total_solves': len(solved_problems),
                    'current_streak': 0, 
                    'max_streak': 0,
                    'recent_submissions': recent_subs
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
                'max_streak': 0,
                'recent_submissions': []
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
            recent_subs = []
            
            submissions.sort(key=lambda x: x.get('epoch_second', 0), reverse=True)
            
            for sub in submissions:
                if sub.get('result') == 'AC':
                    prob_id = sub.get('problem_id')
                    solved_problems.add(prob_id)
                    
                    if len(recent_subs) < 15 and prob_id not in [x['prob_id'] for x in recent_subs]:
                        recent_subs.append({
                            'prob_id': prob_id,
                            'problem_name': prob_id.replace('_', ' ').title(),
                            'problem_url': f"https://atcoder.jp/contests/{sub.get('contest_id')}/tasks/{prob_id}",
                            'timestamp': sub.get('epoch_second', 0)
                        })
                    
            result = {
                'total_solves': len(solved_problems),
                'current_streak': 0,
                'max_streak': 0,
                'recent_submissions': recent_subs
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
      recentAcSubmissionList(username: $username, limit: 15) {
        title
        titleSlug
        timestamp
      }
    }
    """
    try:
        response = requests.post(url, json={'query': query, 'variables': {'username': handle}}, timeout=10)
        if response.status_code == 200:
            data = response.json()
            user_data = data.get('data', {}).get('matchedUser')
            total_solves = 0
            recent_subs = []
            
            if user_data:
                stats = user_data.get('submitStats', {}).get('acSubmissionNum', [])
                for stat in stats:
                    if stat.get('difficulty') == 'All':
                        total_solves = stat.get('count', 0)
                        break
                        
            recent_ac = data.get('data', {}).get('recentAcSubmissionList', [])
            if recent_ac:
                for sub in recent_ac:
                    recent_subs.append({
                        'prob_id': sub.get('titleSlug'),
                        'problem_name': sub.get('title'),
                        'problem_url': f"https://leetcode.com/problems/{sub.get('titleSlug')}/",
                        'timestamp': int(sub.get('timestamp', 0))
                    })
                
            result = {
                'total_solves': total_solves,
                'current_streak': 0,
                'max_streak': 0,
                'recent_submissions': recent_subs
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
        
        # Update Recent Submissions
        recent_subs_data = stats.get('recent_submissions', [])
        if recent_subs_data:
            # Clear old ones
            RecentSubmission.objects.filter(handle=user_handle).delete()
            # Bulk create new ones
            objs = []
            for sub in recent_subs_data:
                dt = datetime.fromtimestamp(sub['timestamp'], tz=timezone.utc)
                objs.append(RecentSubmission(
                    handle=user_handle,
                    problem_name=sub['problem_name'],
                    problem_url=sub['problem_url'],
                    timestamp=dt
                ))
            RecentSubmission.objects.bulk_create(objs)
            
        return True
    return False
