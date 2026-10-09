from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'List admin accounts that are not assigned to a school; does not modify data.'

    def handle(self, *args, **options):
        users = get_user_model().objects.filter(role='admin', school__isnull=True).order_by('username')
        self.stdout.write('id,username,email,is_superuser')
        count = 0
        for user in users.iterator():
            self.stdout.write(f'{user.pk},{user.username},{user.email},{str(user.is_superuser).lower()}')
            count += 1
        self.stdout.write(self.style.WARNING(f'Found {count} admin account(s) without a school; no records changed.'))
