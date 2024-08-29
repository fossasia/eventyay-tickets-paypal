from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='ReferencedPayPalObject',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ('reference', models.CharField(db_index=True, max_length=190, unique=True)),
            ],
        ),
    ]
