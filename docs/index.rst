django-program
==============

.. rst-class:: lead

   Modern conference management for Django - registration, ticketing, Pretalx schedule sync, sponsors, and program activities.

----

**django-program** is a pluggable Django app for running conferences. It covers the
full lifecycle: defining ticket types and add-ons, processing payments through Stripe,
syncing speaker schedules from Pretalx, managing sponsors, and coordinating program
activities like sprints, tutorials, and open spaces.

Built for PyCon US but designed to work for any conference that uses Django.

.. grid:: 1 1 2 2
   :gutter: 2

   .. grid-item-card:: Getting Started
      :link: getting-started/index
      :link-type: doc

      Install django-program and bootstrap your first conference from a TOML config file.

   .. grid-item-card:: Configuration
      :link: configuration
      :link-type: doc

      The TOML bootstrap schema and Django settings reference.

   .. grid-item-card:: Registration Flow
      :link: registration-flow
      :link-type: doc

      How the cart, checkout, and Stripe payment pipeline works end to end.

   .. grid-item-card:: Pretalx Integration
      :link: pretalx-integration
      :link-type: doc

      Speaker and schedule sync architecture, schema regeneration, and the pretalx-client package.

   .. grid-item-card:: API Reference
      :link: api/index
      :link-type: doc

      Autodoc reference for all public modules.


Key Features
------------

- **Ticket Sales** -- Ticket types with availability windows, stock limits, per-user caps, and voucher-gated access
- **Cart & Checkout** -- Expiring carts, voucher discounts (percentage, fixed, comp), Stripe PaymentIntents confirmed via Stripe.js
- **Pretalx Sync** -- Typed HTTP client with automatic /talks/ fallback, multilingual field handling, and weekly drift detection
- **Sponsors** -- Sponsor levels, benefits, comp vouchers auto-generated on sponsor creation
- **Program Activities** -- Sprints, tutorials, open spaces with signup caps, waitlisting, and travel grants
- **Management Dashboard** -- Organizer-facing SSE-powered import/sync UI
- **TOML Bootstrap** -- Define an entire conference (sections, tickets, add-ons, sponsor levels) in a single file


Quick Start
-----------

.. code-block:: bash

   uv add django-program

.. code-block:: python

   # settings.py
   INSTALLED_APPS = [
       ...,
       "django_program.conference",
       "django_program.registration",
       "django_program.pretalx",
       "django_program.sponsors",
       "django_program.programs",
       "django_program.manage",
   ]

   DJANGO_PROGRAM = {
       "stripe": {
           "secret_key": "sk_test_...",
           "publishable_key": "pk_test_...",
           "webhook_secret": "whsec_...",
       },
       "pretalx": {
           "base_url": "https://pretalx.com",
           "token": "your-api-token",
       },
       "currency": "USD",
       "currency_symbol": "$",
   }


.. toctree::
   :maxdepth: 2
   :hidden:
   :caption: Learn

   getting-started/index
   configuration
   registration-flow

.. toctree::
   :maxdepth: 2
   :hidden:
   :caption: Reference

   pretalx-integration
   api/index
   changelog

.. toctree::
   :hidden:
   :caption: Packages

   pretalx-client docs <https://jacobcoffee.github.io/django-program/pretalx-client/>

.. toctree::
   :hidden:
   :caption: Project

   GitHub <https://github.com/JacobCoffee/django-program>
   PyPI <https://pypi.org/project/django-program/>


Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
