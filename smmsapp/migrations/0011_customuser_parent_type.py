# Generated by Django 5.0.6 on 2025-02-09 07:27

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smmsapp', '0010_school_remove_customuser_school_name_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='parent_type',
            field=models.CharField(blank=True, choices=[('mother', 'Mother'), ('father', 'Father'), ('guardian', 'Guardian')], default='mother', max_length=10, null=True),
        ),
    ]
