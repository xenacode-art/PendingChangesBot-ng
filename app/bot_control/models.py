from django.db import models


class BotStatus(models.Model):
    """Tracks the current state of the PendingChangesBot"""

    is_running = models.BooleanField(default=False)
    process_id = models.IntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    stopped_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    last_activity = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bot_status"
        verbose_name = "Bot Status"
        verbose_name_plural = "Bot Statuses"

    def __str__(self):
        status = "Running" if self.is_running else "Stopped"
        return f"Bot Status: {status}"

    @classmethod
    def get_current_status(cls):
        """Get or create the singleton status record"""
        status, created = cls.objects.get_or_create(pk=1)
        return status
