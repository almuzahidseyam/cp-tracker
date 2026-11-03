from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from tracker.models import LoginChallenge, RequestBudget


class Command(BaseCommand):
    help = (
        "Remove login challenges expired for over two days and old rate-limit buckets."
    )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=2)
        challenges, _ = LoginChallenge.objects.filter(expires_at__lt=cutoff).delete()
        budgets, _ = (
            RequestBudget.objects.filter(created_at__lt=cutoff)
            .exclude(window=0)
            .delete()
        )
        self.stdout.write(
            f"Removed {challenges} expired challenges and {budgets} old budget records."
        )
