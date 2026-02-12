from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("program_conference", "0002_encrypt_stripe_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="conference",
            name="address",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
    ]
