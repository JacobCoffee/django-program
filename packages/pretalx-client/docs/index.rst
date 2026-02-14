pretalx-client
==============

.. rst-class:: lead

   A typed Python client for the Pretalx REST API. No Django required.

----

**pretalx-client** talks to the `Pretalx <https://pretalx.com>`_ conference management
API and gives you back frozen dataclasses instead of nested dicts. It handles pagination,
multilingual field extraction, and the ``/talks/`` vs ``/submissions/`` endpoint
inconsistency so you don't have to.

The package depends only on ``httpx``. Install it anywhere Python runs.

.. code-block:: python

   from pretalx_client import PretalxClient

   client = PretalxClient("pycon-us-2026", api_token="abc123")

   for speaker in client.fetch_speakers():
       print(f"{speaker.name} ({speaker.code})")

   for talk in client.fetch_talks():
       print(f"{talk.title} -- {talk.submission_type}")

.. grid:: 1 1 3 3
   :gutter: 2

   .. grid-item-card:: Getting Started
      :link: getting-started/index
      :link-type: doc

      Install the package and make your first API call in under a minute.

   .. grid-item-card:: API Reference
      :link: api/index
      :link-type: doc

      Complete autodoc reference for every public class, function, and module.

   .. grid-item-card:: Architecture
      :link: architecture
      :link-type: doc

      Three-layer design, adapter patterns, and the generated HTTP layer.


What It Does
------------

- **Typed responses** -- ``PretalxSpeaker``, ``PretalxTalk``, ``PretalxSlot`` frozen dataclasses with ``from_api()`` constructors
- **Automatic pagination** -- follows ``next`` links until all pages are collected
- **Multilingual fields** -- extracts the ``en`` value from Pretalx's ``{"en": "...", "de": "..."}`` dicts
- **Endpoint fallback** -- tries ``/talks/`` first, falls back to ``/submissions/?state=confirmed`` + ``accepted`` when the endpoint 404s
- **ID-to-name resolution** -- maps integer IDs for rooms, tracks, submission types, and tags to display names
- **Event discovery** -- ``PretalxClient.fetch_events()`` lists all events visible to your token
- **No framework dependency** -- just ``httpx`` under the hood


.. toctree::
   :maxdepth: 2
   :hidden:
   :caption: Learn

   getting-started/index

.. toctree::
   :maxdepth: 2
   :hidden:
   :caption: Reference

   api/index
   architecture

.. toctree::
   :hidden:
   :caption: Project

   GitHub <https://github.com/JacobCoffee/django-program>
   PyPI <https://pypi.org/project/pretalx-client/>


Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
