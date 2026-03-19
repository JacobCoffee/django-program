"""URL patterns for purchase order management.

Included under ``<slug:conference_slug>/purchase-orders/`` in the main
management URL configuration.
"""

from django.urls import path

from django_program.manage.views_purchase_orders import (
    PurchaseOrderCancelView,
    PurchaseOrderCreateView,
    PurchaseOrderDetailView,
    PurchaseOrderInvoiceView,
    PurchaseOrderIssueCreditView,
    PurchaseOrderListView,
    PurchaseOrderQBOInvoiceView,
    PurchaseOrderRecordPaymentView,
    PurchaseOrderSendView,
    PurchaseOrderStripeInvoiceView,
)

urlpatterns = [
    path("", PurchaseOrderListView.as_view(), name="purchase-order-list"),
    path("add/", PurchaseOrderCreateView.as_view(), name="purchase-order-add"),
    path("<int:pk>/", PurchaseOrderDetailView.as_view(), name="purchase-order-detail"),
    path("<int:pk>/payment/", PurchaseOrderRecordPaymentView.as_view(), name="purchase-order-payment"),
    path("<int:pk>/credit/", PurchaseOrderIssueCreditView.as_view(), name="purchase-order-credit"),
    path("<int:pk>/cancel/", PurchaseOrderCancelView.as_view(), name="purchase-order-cancel"),
    path("<int:pk>/send/", PurchaseOrderSendView.as_view(), name="purchase-order-send"),
    path("<int:pk>/invoice/", PurchaseOrderInvoiceView.as_view(), name="purchase-order-invoice"),
    path("<int:pk>/stripe-invoice/", PurchaseOrderStripeInvoiceView.as_view(), name="purchase-order-stripe-invoice"),
    path("<int:pk>/qbo-invoice/", PurchaseOrderQBOInvoiceView.as_view(), name="purchase-order-qbo-invoice"),
]
