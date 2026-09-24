# CP Tracker 🚀

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.12-blue)
![Django](https://img.shields.io/badge/Django-6.1-green)

A modern, open-source competitive programming tracker built as a **StopStalk alternative**. It helps you track your (and your friends') coding progress across multiple platforms in one unified dashboard.

## 🌟 Features

- **Multi-Platform Support**: Live tracking for **Codeforces**, **LeetCode**, and **AtCoder**.
- **Live Leaderboard**: Compare total solves with friends dynamically.
- **Recent Submissions Timeline**: See what your friends are solving in real-time.
- **Secure Authentication**: OTP-based login (passwordless) with custom user models.
- **Production Ready**: Fully configured for Vercel/Render with PostgreSQL via dj-database-url.

## 🛠️ Tech Stack

- **Backend**: Django 6.1 (Python)
- **Database**: PostgreSQL (Production) / SQLite (Local)
- **Scraping/API**: GraphQL (LeetCode), Regex parsing (CodeChef), REST (Codeforces)
- **Deployment**: Configured for Vercel Serverless Functions

## 🚀 Quick Start (Local Setup)

1. **Clone the repo**:
   \\\ash
   git clone https://github.com/almuzahidseyam/cp-tracker.git
   cd cp-tracker
   \\\

2. **Create a virtual environment**:
   \\\ash
   python -m venv venv
   source venv/bin/activate  # On Windows: .\venv\Scripts\activate
   \\\

3. **Install dependencies**:
   \\\ash
   pip install -r requirements.txt
   \\\

4. **Run Migrations & Start**:
   \\\ash
   python manage.py migrate
   python manage.py runserver
   \\\

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
