"""Minimal URL configuration for tests."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("manage/", include("django_program.manage.urls")),
    path("<slug:conference_slug>/program/", include("django_program.pretalx.urls")),
    path("<slug:conference_slug>/sponsors/", include("django_program.sponsors.urls")),
]
