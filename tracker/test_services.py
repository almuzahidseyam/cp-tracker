from django.test import TestCase
from unittest.mock import patch, MagicMock
from .services import fetch_codeforces_data, fetch_leetcode_data

class APIServiceTests(TestCase):
    @patch('tracker.services.requests.get')
    def test_fetch_codeforces_data_success(self, mock_get):
        # Mock the CF user.status response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'status': 'OK',
            'result': [
                {'verdict': 'OK', 'problem': {'contestId': 1, 'index': 'A', 'name': 'Test Prob 1'}, 'creationTimeSeconds': 1000},
                {'verdict': 'WRONG_ANSWER', 'problem': {'contestId': 1, 'index': 'B', 'name': 'Test Prob 2'}, 'creationTimeSeconds': 2000},
            ]
        }
        
        # We also need to mock user.info if we want full testing, but since we test multiple requests, 
        # let's just make the mock_get return a sequence of responses using side_effect.
        
        mock_status = MagicMock()
        mock_status.status_code = 200
        mock_status.json.return_value = {
            'status': 'OK',
            'result': [
                {'verdict': 'OK', 'problem': {'contestId': 1, 'index': 'A', 'name': 'Test Prob'}, 'creationTimeSeconds': 1000}
            ]
        }
        
        mock_info = MagicMock()
        mock_info.status_code = 200
        mock_info.json.return_value = {
            'status': 'OK',
            'result': [{'rating': 1500, 'rank': 'specialist', 'maxRating': 1600}]
        }
        
        mock_get.side_effect = [mock_status, mock_info]
        
        data = fetch_codeforces_data('testuser')
        
        self.assertIsNotNone(data)
        self.assertEqual(data['total_solves'], 1)
        self.assertEqual(data['rating'], 1500)
        self.assertEqual(data['rank'], 'Specialist')

    @patch('tracker.services.requests.post')
    def test_fetch_leetcode_data_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'data': {
                'matchedUser': {
                    'submitStats': {
                        'acSubmissionNum': [
                            {'difficulty': 'All', 'count': 42}
                        ]
                    }
                },
                'userContestRanking': {
                    'rating': 1650,
                    'badge': {'name': 'Knight'}
                },
                'recentAcSubmissionList': []
            }
        }
        mock_post.return_value = mock_response
        
        data = fetch_leetcode_data('testuser')
        
        self.assertIsNotNone(data)
        self.assertEqual(data['total_solves'], 42)
        self.assertEqual(data['rating'], 1650)
        self.assertEqual(data['rank'], 'Knight')
