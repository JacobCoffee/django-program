from django_program.pretalx.client import PretalxClient


def test_client_normalizes_base_url_with_api_suffix() -> None:
    client = PretalxClient(
        "pycon-us-2027",
        base_url="https://pretalx.example.com/api/",
    )

    assert client.base_url == "https://pretalx.example.com"
    assert client.api_url == "https://pretalx.example.com/api/events/pycon-us-2027/"


def test_client_keeps_root_base_url() -> None:
    client = PretalxClient(
        "pycon-us-2027",
        base_url="https://pretalx.example.com",
    )

    assert client.base_url == "https://pretalx.example.com"
    assert client.api_url == "https://pretalx.example.com/api/events/pycon-us-2027/"
