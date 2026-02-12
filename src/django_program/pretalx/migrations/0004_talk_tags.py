from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("program_pretalx", "0003_add_scheduleslot_unique_constraint"),
    ]

    operations = [
        migrations.AddField(
            model_name="talk",
            name="tags",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
