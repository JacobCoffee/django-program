"""URL patterns for overrides and submission type defaults.

Included from the main management URL config under the
``<slug:conference_slug>/overrides/`` prefix.
"""

from django.urls import path

from django_program.manage.views_overrides import (
    RoomOverrideCreateView,
    RoomOverrideEditView,
    RoomOverrideListView,
    SpeakerOverrideCreateView,
    SpeakerOverrideEditView,
    SpeakerOverrideListView,
    SponsorOverrideCreateView,
    SponsorOverrideEditView,
    SponsorOverrideListView,
    SubmissionTypeDefaultCreateView,
    SubmissionTypeDefaultEditView,
    SubmissionTypeDefaultListView,
    TalkOverrideCreateView,
    TalkOverrideEditView,
    TalkOverrideListView,
)

urlpatterns = [
    # Talk overrides
    path("talks/", TalkOverrideListView.as_view(), name="override-list"),
    path("talks/add/", TalkOverrideCreateView.as_view(), name="override-add"),
    path("talks/<int:pk>/edit/", TalkOverrideEditView.as_view(), name="override-edit"),
    # Speaker overrides
    path("speakers/", SpeakerOverrideListView.as_view(), name="speaker-override-list"),
    path("speakers/add/", SpeakerOverrideCreateView.as_view(), name="speaker-override-add"),
    path("speakers/<int:pk>/edit/", SpeakerOverrideEditView.as_view(), name="speaker-override-edit"),
    # Room overrides
    path("rooms/", RoomOverrideListView.as_view(), name="room-override-list"),
    path("rooms/add/", RoomOverrideCreateView.as_view(), name="room-override-add"),
    path("rooms/<int:pk>/edit/", RoomOverrideEditView.as_view(), name="room-override-edit"),
    # Sponsor overrides
    path("sponsors/", SponsorOverrideListView.as_view(), name="sponsor-override-list"),
    path("sponsors/add/", SponsorOverrideCreateView.as_view(), name="sponsor-override-add"),
    path("sponsors/<int:pk>/edit/", SponsorOverrideEditView.as_view(), name="sponsor-override-edit"),
    # Submission type defaults
    path("type-defaults/", SubmissionTypeDefaultListView.as_view(), name="type-default-list"),
    path("type-defaults/add/", SubmissionTypeDefaultCreateView.as_view(), name="type-default-add"),
    path("type-defaults/<int:pk>/edit/", SubmissionTypeDefaultEditView.as_view(), name="type-default-edit"),
]
