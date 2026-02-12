"""Default Pretalx profile: standard track semantics."""

from django_program.pretalx.profiles.base import PretalxConferenceProfile


class DefaultPretalxProfile(PretalxConferenceProfile):
    """Use Pretalx's standard interpretation of tracks."""

    name = "default"
