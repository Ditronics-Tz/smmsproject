import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('smmsapp', '0016_insightflag')]

    operations = [
        migrations.CreateModel(
            name='DailyMenu',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('date', models.DateField(db_index=True)),
                ('meal_type', models.CharField(choices=[('breakfast', 'Breakfast'), ('lunch', 'Lunch'), ('dinner', 'Dinner')], max_length=50)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='smmsapp.customuser')),
            ],
            options={'ordering': ['date', 'meal_type'], 'constraints': [models.UniqueConstraint(fields=('date', 'meal_type'), name='uniq_daily_menu_date_meal')]},
        ),
        migrations.CreateModel(
            name='DailyMenuItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('price_override', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='daily_menu_entries', to='smmsapp.canteenitem')),
                ('menu', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='smmsapp.dailymenu')),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('menu', 'item'), name='uniq_daily_menu_item')]},
        ),
    ]
