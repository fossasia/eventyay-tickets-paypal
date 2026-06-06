Eventyay PayPal
================

Eventyay PayPal is a payment plugin for `Eventyay <https://github.com/fossasia/eventyay>`_. It allows event organisers to accept payments through PayPal.

The plugin adds a ``PayPal`` payment provider to Eventyay. It supports PayPal checkout, PayPal sandbox mode, direct API credentials, PayPal Connect based onboarding, order creation, payment capture, payment return handling, webhook processing, refund handling, and privacy related payment data shredding.

Project status
--------------

Eventyay PayPal is maintained as part of the Eventyay plugin ecosystem.

The plugin package is named ``eventyay-paypal`` and the Python module is named ``eventyay_paypal``.

Main features
-------------

- PayPal payment support for Eventyay events
- PayPal payment provider in the Eventyay payment settings
- PayPal sandbox mode for testing
- Direct configuration with PayPal Client ID and Secret
- PayPal Connect based account onboarding
- Event level PayPal account connection and disconnection
- PayPal order creation during checkout
- Buyer redirection to PayPal approval flow
- Return and abort handling after the buyer leaves PayPal
- Webhook endpoint for PayPal payment events
- Payment capture and confirmation handling
- Refund and partial refund support
- Payment status logging for organiser review
- Public checkout form integration
- Organiser control interface integration
- Privacy oriented payment data shredding
- Internationalisation support through Django translation files

Requirements
------------

- Python 3.11 or newer
- A working Eventyay development or production setup
- A PayPal business account or PayPal sandbox account
- PayPal REST API credentials or PayPal Connect configuration
- The Eventyay plugin build tooling used by the package

Installation for development
----------------------------

Use this setup when developing the plugin together with a local Eventyay installation.

1. Set up Eventyay
~~~~~~~~~~~~~~~~~~

First make sure you have a working Eventyay development setup.

See the Eventyay repository:

`Eventyay <https://github.com/fossasia/eventyay>`_

2. Clone this repository
~~~~~~~~~~~~~~~~~~~~~~~~

Clone the plugin repository next to your Eventyay checkout or into the local plugin directory used by your Eventyay development setup.

.. code-block:: bash

   git clone https://github.com/fossasia/eventyay-paypal.git
   cd eventyay-paypal

3. Activate the Eventyay virtual environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Activate the virtual environment used by your Eventyay installation.

Example:

.. code-block:: bash

   cd ../eventyay/app
   . .venv/bin/activate

4. Install the plugin in editable mode
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

From the ``eventyay-paypal`` directory, install the plugin in editable mode.

.. code-block:: bash

   pip install -e .

If your Eventyay development setup uses ``uv``, you can also use:

.. code-block:: bash

   uv pip install -e .

5. Apply migrations
~~~~~~~~~~~~~~~~~~~

Run migrations from the Eventyay app directory.

.. code-block:: bash

   python manage.py migrate

6. Compile translations
~~~~~~~~~~~~~~~~~~~~~~~

Compile translation files from the plugin directory.

.. code-block:: bash

   make

7. Restart Eventyay
~~~~~~~~~~~~~~~~~~~

Restart the Eventyay development server and worker processes if they are running.

.. code-block:: bash

   python manage.py runserver

If you use Docker for Eventyay development, restart the relevant containers after installing or changing the plugin.

Using the plugin
----------------

1. Open the Eventyay organiser interface.
2. Open the event where PayPal payments should be enabled.
3. Go to the payment provider settings.
4. Enable the PayPal payment provider.
5. Connect the event to PayPal or enter PayPal API credentials, depending on the configured setup.
6. Configure sandbox or live mode.
7. Save the payment settings.
8. Test the checkout flow with a test order before using the provider for a live event.

PayPal configuration modes
--------------------------

The plugin supports two main configuration modes.

PayPal Connect
~~~~~~~~~~~~~~

PayPal Connect allows an organiser to connect an event to a PayPal account through the Eventyay payment settings.

When PayPal Connect is configured globally, the organiser sees a connect button in the event payment settings. After the account has been connected successfully, Eventyay stores the PayPal account reference for the event.

Global PayPal Connect settings include:

- ``payment_paypal_connect_client_id``
- ``payment_paypal_connect_secret_key``
- ``payment_paypal_connect_endpoint``

The endpoint can be set to ``live`` or ``sandbox``.

Direct API credentials
~~~~~~~~~~~~~~~~~~~~~~

The plugin can also be configured with direct PayPal REST API credentials at event level.

Event level payment settings include:

- ``client_id``
- ``secret``
- ``endpoint``
- ``webhook_id``
- ``prefix``

The endpoint can be set to ``live`` or ``sandbox``. The optional reference prefix is added in front of the regular booking reference in PayPal related order data.

Sandbox mode
------------

The plugin supports PayPal sandbox mode. In sandbox mode, organisers can test the payment flow without sending real money.

Use sandbox mode before enabling PayPal for a live event. A PayPal sandbox buyer account is required to complete sandbox checkout tests.

Checkout flow
-------------

During checkout, the plugin creates a PayPal order for the Eventyay payment amount and event currency. The buyer is redirected to the PayPal approval flow and then returned to Eventyay.

After the buyer returns, Eventyay verifies the PayPal order, captures the payment where needed, stores PayPal payment information with the Eventyay order payment, and confirms the payment when the PayPal status allows confirmation.

Webhook flow
------------

The plugin provides webhook endpoints for PayPal notifications. Webhooks are used to receive payment events and update the corresponding Eventyay order payment.

The plugin maps PayPal order and capture references back to Eventyay orders and payments through ``ReferencedPayPalObject``.

Refunds
-------

The plugin supports refunds and partial refunds through the PayPal API.

Refund handling uses the PayPal capture reference stored in the payment data. Completed refunds are marked as done in Eventyay. Pending refunds are kept in transit. Failed refund attempts are logged and shown as payment exceptions.

Supported currencies
--------------------

The plugin defines support for the following currencies:

.. code-block:: text

   AUD BRL CAD CZK DKK EUR HKD HUF INR ILS JPY MYR MXN TWD NZD NOK PHP PLN GBP RUB SGD SEK CHF THB USD

The plugin also marks ``INR`` as a local-only currency.

URLs
----

The plugin registers event specific URLs for PayPal payment handling.

Event URLs include:

.. code-block:: text

   /<organizer>/<event>/paypal/abort/
   /<organizer>/<event>/paypal/return/
   /<organizer>/<event>/paypal/redirect/
   /<organizer>/<event>/paypal/w/<cart_namespace>/abort/
   /<organizer>/<event>/paypal/w/<cart_namespace>/return/
   /<organizer>/<event>/paypal/webhook/

Global plugin URLs include:

.. code-block:: text

   /control/event/<organizer>/<event>/paypal/disconnect/
   /_paypal/webhook/
   /_paypal/oauth_return/

Data model
----------

The plugin stores PayPal references in ``ReferencedPayPalObject``.

The model links an external PayPal reference to:

- The Eventyay order
- The Eventyay payment, if available

This allows PayPal webhook notifications, order details, captures, and refunds to be mapped back to the corresponding Eventyay order and payment.

Development commands
--------------------

Run these commands from the plugin repository unless otherwise noted.

Install the plugin in editable mode:

.. code-block:: bash

   pip install -e .

Compile translations:

.. code-block:: bash

   make

Regenerate translation files:

.. code-block:: bash

   make localegen

Run tests, if tests are available in the checkout:

.. code-block:: bash

   pytest

Package structure
-----------------

Important files and directories:

.. code-block:: text

   .
   ├── eventyay_paypal/
   │   ├── __init__.py        Plugin version
   │   ├── apps.py            Eventyay plugin metadata
   │   ├── models.py          PayPal reference model
   │   ├── payment.py         Payment provider implementation
   │   ├── paypal_rest.py     PayPal REST API request handling
   │   ├── signals.py         Payment provider registration and display hooks
   │   ├── urls.py            Event and global plugin URLs
   │   ├── utils.py           Utility helpers
   │   ├── views.py           Return, redirect, webhook, OAuth and disconnect views
   │   ├── migrations/        Database migrations
   │   ├── templates/         Django templates
   │   └── locale/            Translation files
   ├── plugin.toml            Plugin release and package metadata
   ├── pyproject.toml         Python package metadata
   ├── setup.py               Setuptools entry point
   ├── setup.cfg              Tool configuration placeholder
   ├── MANIFEST.in            Package data inclusion
   ├── Makefile               Translation helper commands
   ├── pytest.ini             Test configuration
   ├── LICENSE                Apache License 2.0
   └── README.rst             Project documentation

Packaging
---------

The package metadata is defined in ``pyproject.toml``.

The package includes:

- Python module ``eventyay_paypal``
- Static files
- Templates
- Locale files
- License file

The version is read from ``eventyay_paypal.__version__``.

Security and privacy notes
--------------------------

The plugin stores PayPal responses as payment information in Eventyay.

The plugin includes a ``shred_payment_info`` implementation that masks sensitive payer information and keeps only selected operational data such as payment IDs, update time, purchase units, payment references, sale IDs, and parent payment references.

Production notes
----------------

Before using the plugin for a live event:

- Test the provider connection with a test event.
- Verify that the PayPal payment method appears correctly in checkout.
- Confirm that the return and abort URLs work correctly.
- Confirm that the webhook endpoint is reachable from PayPal.
- Place a test order and verify that payment confirmation updates the order.
- Test refund and partial refund handling before relying on automatic refunds.
- Confirm that the event currency is supported by PayPal for the relevant PayPal account and country.
- Confirm whether the event should use direct PayPal API credentials or PayPal Connect.
- Switch from sandbox mode to live mode only after the test flow works reliably.

License
-------

Eventyay PayPal is released under the terms of the Apache License 2.0.

See `LICENSE <LICENSE>`_ for the full license text.

Credits
-------

Maintained by the Eventyay team and FOSSASIA.

Links
-----

- `Eventyay <https://github.com/fossasia/eventyay>`_
- `Eventyay PayPal <https://github.com/fossasia/eventyay-paypal>`_
- `PayPal Developer <https://developer.paypal.com/>`_
- `FOSSASIA <https://fossasia.org>`_
