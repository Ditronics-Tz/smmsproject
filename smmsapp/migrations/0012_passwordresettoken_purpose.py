from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smmsapp', '0011_bankdeposit_payment_details'),
    ]

    operations = [
        migrations.AddField(
            model_name='passwordresettoken',
            name='purpose',
            field=models.CharField(
                choices=[('password_reset', 'Password reset'), ('invite', 'Password invite')],
                default='password_reset',
                max_length=20,
            ),
        ),
    ]
