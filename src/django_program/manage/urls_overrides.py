"""URL patterns for Pretalx talk overrides and submission type defaults.

Included from the main management URL config under the
``<slug:conference_slug>/overrides/`` prefix.
"""

from django.urls import path

from django_program.manage.views_overrides import (
    SubmissionTypeDefaultCreateView,
    SubmissionTypeDefaultEditView,
    SubmissionTypeDefaultListView,
    TalkOverrideCreateView,
    TalkOverrideEditView,
    TalkOverrideListView,
)

urlpatterns = [
    path("talks/", TalkOverrideListView.as_view(), name="override-list"),
    path("talks/add/", TalkOverrideCreateView.as_view(), name="override-add"),
    path("talks/<int:pk>/edit/", TalkOverrideEditView.as_view(), name="override-edit"),
    path("type-defaults/", SubmissionTypeDefaultListView.as_view(), name="type-default-list"),
    path("type-defaults/add/", SubmissionTypeDefaultCreateView.as_view(), name="type-default-add"),
    path("type-defaults/<int:pk>/edit/", SubmissionTypeDefaultEditView.as_view(), name="type-default-edit"),
]
