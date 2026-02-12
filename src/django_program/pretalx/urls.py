"""URL configuration for the pretalx integration app.

Provides schedule, talk, and speaker endpoints scoped to a conference slug.
Mount these under a conference-scoped prefix in the host project::

    urlpatterns = [
        path("<slug:conference_slug>/program/", include("django_program.pretalx.urls")),
    ]
"""

from django.urls import path

from django_program.pretalx.views import (
    ScheduleJSONView,
    ScheduleView,
    SpeakerDetailView,
    SpeakerListView,
    TalkDetailView,
)

app_name = "pretalx"

urlpatterns = [
    path("schedule/", ScheduleView.as_view(), name="schedule"),
    path("schedule/data.json", ScheduleJSONView.as_view(), name="schedule-json"),
    path("talks/<slug:pretalx_code>/", TalkDetailView.as_view(), name="talk-detail"),
    path("speakers/", SpeakerListView.as_view(), name="speaker-list"),
    path("speakers/<slug:pretalx_code>/", SpeakerDetailView.as_view(), name="speaker-detail"),
]
