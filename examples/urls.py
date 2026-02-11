"""URL configuration for the example development server."""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="admin:index"), name="root"),
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="admin/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("manage/", include("django_program.manage.urls")),
    path("<slug:conference_slug>/program/", include("django_program.pretalx.urls")),
]
