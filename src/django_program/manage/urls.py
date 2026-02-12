"""URL configuration for the conference management dashboard.

Mount under a prefix in the host project::

    urlpatterns = [
        path("manage/", include("django_program.manage.urls")),
    ]
"""

from django.urls import path

from django_program.manage.views import (
    ConferenceEditView,
    ConferenceListView,
    DashboardView,
    ImportFromPretalxView,
    ImportPretalxStreamView,
    PretalxEventSearchView,
    RoomCreateView,
    RoomEditView,
    RoomListView,
    ScheduleSlotEditView,
    ScheduleSlotListView,
    SectionCreateView,
    SectionEditView,
    SectionListView,
    SpeakerDetailView,
    SpeakerListView,
    SponsorCreateView,
    SponsorEditView,
    SponsorLevelCreateView,
    SponsorLevelEditView,
    SponsorLevelListView,
    SponsorManageListView,
    SyncPretalxStreamView,
    SyncPretalxView,
    TalkDetailView,
    TalkEditView,
    TalkListView,
)

app_name = "manage"

urlpatterns = [
    path("", ConferenceListView.as_view(), name="conference-list"),
    path("import/", ImportFromPretalxView.as_view(), name="import-pretalx"),
    path("import/stream/", ImportPretalxStreamView.as_view(), name="import-pretalx-stream"),
    path("api/pretalx-events/", PretalxEventSearchView.as_view(), name="pretalx-event-search"),
    path("<slug:conference_slug>/", DashboardView.as_view(), name="dashboard"),
    path("<slug:conference_slug>/edit/", ConferenceEditView.as_view(), name="conference-edit"),
    path("<slug:conference_slug>/sync/", SyncPretalxView.as_view(), name="sync-pretalx"),
    path("<slug:conference_slug>/sync/stream/", SyncPretalxStreamView.as_view(), name="sync-pretalx-stream"),
    path("<slug:conference_slug>/sections/", SectionListView.as_view(), name="section-list"),
    path("<slug:conference_slug>/sections/add/", SectionCreateView.as_view(), name="section-add"),
    path(
        "<slug:conference_slug>/sections/<int:pk>/edit/",
        SectionEditView.as_view(),
        name="section-edit",
    ),
    path("<slug:conference_slug>/rooms/", RoomListView.as_view(), name="room-list"),
    path("<slug:conference_slug>/rooms/add/", RoomCreateView.as_view(), name="room-add"),
    path(
        "<slug:conference_slug>/rooms/<int:pk>/edit/",
        RoomEditView.as_view(),
        name="room-edit",
    ),
    path("<slug:conference_slug>/speakers/", SpeakerListView.as_view(), name="speaker-list"),
    path("<slug:conference_slug>/speakers/<int:pk>/", SpeakerDetailView.as_view(), name="speaker-detail"),
    path("<slug:conference_slug>/talks/", TalkListView.as_view(), name="talk-list"),
    path("<slug:conference_slug>/talks/type/<slug:type_slug>/", TalkListView.as_view(), name="talk-list-by-type"),
    path("<slug:conference_slug>/talks/<int:pk>/", TalkDetailView.as_view(), name="talk-detail"),
    path(
        "<slug:conference_slug>/talks/<int:pk>/edit/",
        TalkEditView.as_view(),
        name="talk-edit",
    ),
    path("<slug:conference_slug>/schedule/", ScheduleSlotListView.as_view(), name="schedule-list"),
    path(
        "<slug:conference_slug>/schedule/<int:pk>/edit/",
        ScheduleSlotEditView.as_view(),
        name="slot-edit",
    ),
    path("<slug:conference_slug>/sponsor-levels/", SponsorLevelListView.as_view(), name="sponsor-level-list"),
    path("<slug:conference_slug>/sponsor-levels/add/", SponsorLevelCreateView.as_view(), name="sponsor-level-add"),
    path(
        "<slug:conference_slug>/sponsor-levels/<int:pk>/edit/",
        SponsorLevelEditView.as_view(),
        name="sponsor-level-edit",
    ),
    path("<slug:conference_slug>/sponsors/", SponsorManageListView.as_view(), name="sponsor-manage-list"),
    path("<slug:conference_slug>/sponsors/add/", SponsorCreateView.as_view(), name="sponsor-add"),
    path(
        "<slug:conference_slug>/sponsors/<int:pk>/edit/",
        SponsorEditView.as_view(),
        name="sponsor-edit",
    ),
]
