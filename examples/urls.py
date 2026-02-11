"""URL configuration for the example development server."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("<slug:conference_slug>/program/", include("django_program.pretalx.urls")),
]
