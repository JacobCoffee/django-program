"""Sphinx configuration for pretalx-client documentation."""

import os
import sys
from datetime import datetime
from importlib.metadata import version as get_version

sys.path.insert(0, os.path.abspath("../src"))

project = "pretalx-client"
copyright = f"{datetime.now().year}, Jacob Coffee"
author = "Jacob Coffee"
try:
    release = get_version("pretalx-client")
except Exception:  # noqa: BLE001
    release = "0.1.0"
version = ".".join(release.split(".")[:2])

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",
    "sphinx_copybutton",
    "sphinx_design",
    "sphinx_autodoc_typehints",
    "myst_parser",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
master_doc = "index"
language = "en"

# Napoleon (Google-style docstrings)
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_references = False
# Use :ivar: for Attributes sections to avoid duplicate object descriptions
# with autodoc's dataclass field introspection.
napoleon_use_ivar = True
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_use_keyword = True
napoleon_preprocess_types = True
napoleon_attr_annotations = True

# Autodoc
autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
    "exclude-members": "__weakref__",
    "show-inheritance": True,
}
autodoc_class_signature = "separated"
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented"
autodoc_inherit_docstrings = True

autosummary_generate = True
autosummary_imported_members = False

# Exclude generated subpackage from autosummary recursion
autosummary_filename_map = {}

# Intersphinx inventory warnings are expected when building standalone.
# The autodoc signature warnings are from a circular TYPE_CHECKING import
# in adapters/talks.py (PretalxClient); the function still documents fine.
suppress_warnings = ["myst.header", "ref.python", "autodoc"]

typehints_fully_qualified = False
always_document_param_types = True
typehints_document_rtype = True
typehints_use_rtype = True

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "httpx": ("https://www.python-httpx.org/", None),
    "django_program": (
        "https://jacobcoffee.github.io/django-program/",
        ("../../../docs/_build/html/objects.inv", None),
    ),
}

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "html_admonition",
    "html_image",
    "replacements",
    "smartquotes",
    "strikethrough",
    "substitution",
    "tasklist",
]
myst_heading_anchors = 3

copybutton_prompt_text = r">>> |\.\.\. |\$ |In \[\d*\]: | {2,5}\.\.\.: | {5,8}: "
copybutton_prompt_is_regexp = True
copybutton_remove_prompts = True

# HTML
html_theme = "shibuya"
html_title = "pretalx-client"
html_static_path = ["_static"]
html_css_files = ["custom.css"]

html_theme_options = {
    "accent_color": "blue",
    "github_url": "https://github.com/JacobCoffee/django-program",
    "nav_links": [
        {"title": "Pretalx", "url": "https://pretalx.com/"},
        {"title": "django-program", "url": "https://github.com/JacobCoffee/django-program"},
    ],
}

latex_elements = {"papersize": "letterpaper", "pointsize": "10pt"}
