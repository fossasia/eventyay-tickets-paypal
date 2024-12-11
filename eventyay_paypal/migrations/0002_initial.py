import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('eventyay_paypal', '0001_initial'),
        ('pretixbase', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='referencedpaypalobject',
            name='order',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='pretixbase.order'),
        ),
        migrations.AddField(
            model_name='referencedpaypalobject',
            name='payment',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='pretixbase.orderpayment'),
        ),
    ]
