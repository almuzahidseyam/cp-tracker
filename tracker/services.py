import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

def fetch_codeforces_data(handle):
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
                        # Unique problem identifier: contestId + index
                        prob_id = f"{prob.get('contestId')}{prob.get('index')}"
                        solved_problems.add(prob_id)
                        
                return {
                    'total_solves': len(solved_problems),
                    # Streaks can be calculated by grouping by creationTimeSeconds, but keeping it simple for now
                    'current_streak': 0, 
                    'max_streak': 0
                }
    except Exception as e:
        print(f"Error fetching CF data: {e}")
    return None

def fetch_codechef_data(handle):
    url = f"https://www.codechef.com/users/{handle}"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'lxml')
            # In CodeChef, fully solved problems are usually indicated in the profile rating section
            # For exact scraping, we search for the specific text
            rating_section = soup.find('div', class_='rating-data-section')
            total_solves = 0
            if rating_section:
                h3_tags = rating_section.find_all('h3')
                for h3 in h3_tags:
                    if 'Fully Solved' in h3.text:
                        # Extract the number from 'Fully Solved (123)'
                        num_str = h3.text.replace('Fully Solved', '').strip('() ')
                        if num_str.isdigit():
                            total_solves = int(num_str)
                            break
            
            return {
                'total_solves': total_solves,
                'current_streak': 0,
                'max_streak': 0
            }
    except Exception as e:
        print(f"Error fetching CodeChef data: {e}")
    return None

def fetch_atcoder_data(handle):
    # Using Kenkoooo API
    url = f"https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?user={handle}&from_second=0"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            submissions = response.json()
            solved_problems = set()
            for sub in submissions:
                if sub.get('result') == 'AC':
                    solved_problems.add(sub.get('problem_id'))
                    
            return {
                'total_solves': len(solved_problems),
                'current_streak': 0,
                'max_streak': 0
            }
    except Exception as e:
        print(f"Error fetching AtCoder data: {e}")
    return None

def update_user_handle_stats(user_handle):
    stats = None
    if user_handle.platform == 'CF':
        stats = fetch_codeforces_data(user_handle.handle)
    elif user_handle.platform == 'CC':
        stats = fetch_codechef_data(user_handle.handle)
    elif user_handle.platform == 'AC':
        stats = fetch_atcoder_data(user_handle.handle)
        
    if stats:
        user_handle.total_solves = stats.get('total_solves', 0)
        user_handle.current_streak = stats.get('current_streak', 0)
        user_handle.max_streak = stats.get('max_streak', 0)
        user_handle.save()
        return True
    return False
