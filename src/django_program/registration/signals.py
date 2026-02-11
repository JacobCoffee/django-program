"""Custom signals for the registration app.

Signals:
    order_paid: Sent when an order transitions to PAID status.
        Sender: The ``Order`` class.
        Kwargs:
            order: The ``Order`` instance that was paid.
            user: The user who owns the order.
"""

from django.dispatch import Signal

order_paid = Signal()
