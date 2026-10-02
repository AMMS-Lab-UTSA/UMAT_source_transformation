"""A licence file is classified by its notice and title, not by a body search.

Regression (Scout, B1): ``classify_license_text`` searched the whole text with
AGPL first, and the GPL-3.0 text names the GNU Affero licence in its section 13,
so every GPL-3.0 file read as AGPL-3.0 (frodal/SCMM-hypo went into the registry
as AGPL-3.0; makkemal/NGIMASEM's file read the same). The same search read
LGPL-3.0 as GPL-3.0 (it incorporates "version 3 of the GNU General Public
License"), GPL-2.0 as LGPL-3.0 and LGPL-2.1 as LGPL-3.0.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from umat_oti.corpus.acquire import classify_license_text

CACHE = Path("/home/ammslab3/softwarex_work/discovery_cache")
COMMON = Path("/usr/share/common-licenses")


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")


@pytest.mark.parametrize("relative,expected", [
    # notice above the full GPL-3.0 text: "either version 3 ... or any later version"
    ("frodal__SCMM-hypo/LICENSE.md", "GPL-3.0-or-later"),
    ("makkemal__NGIMASEM/license.md", "GPL-3.0"),
    ("Balbest__igUEL-public/LICENSE.txt", "MIT"),
    ("bibekanandadatta__Abaqus-UEL-Hyperelasticity/LICENSE.md", "BSD-3-Clause"),
    ("PeriHub__PeriLab.jl/LICENSE.md", "BSD-3-Clause"),
    ("mhogg__bonemapy/LICENSE.txt", "MIT"),
    ("tengzhang48__CoupFE/LICENSE-DOCS.md", None),
])
def test_the_cached_licence_files(relative, expected):
    path = CACHE / relative
    if not path.is_file():
        pytest.skip(f"{path} not in the acquisition cache")
    assert classify_license_text(_read(path)) == expected


@pytest.mark.parametrize("name,expected", [
    ("GPL-3", "GPL-3.0"), ("GPL-2", "GPL-2.0"), ("LGPL-3", "LGPL-3.0"),
    ("LGPL-2.1", "LGPL-2.1"), ("LGPL-2", "LGPL-2.0"), ("Apache-2.0", "Apache-2.0"),
    ("BSD", "BSD-3-Clause"),
])
def test_the_canonical_texts_shipped_with_the_system(name, expected):
    path = COMMON / name
    if not path.is_file():
        pytest.skip(f"{path} not installed")
    assert classify_license_text(_read(path)) == expected


def test_the_gpl3_body_naming_affero_does_not_make_it_agpl():
    path = COMMON / "GPL-3"
    text = _read(path) if path.is_file() else (
        "GNU GENERAL PUBLIC LICENSE\n Version 3, 29 June 2007\n" + "x\n" * 200
        + "  13. Use with the GNU Affero General Public License.\n")
    assert "affero" in text.lower()
    assert classify_license_text(text) == "GPL-3.0"


def test_an_agpl_text_is_agpl_although_its_body_names_the_gpl():
    """No AGPL licence file is in the cache; this is the AGPL-3.0 title block
    and its section 13 heading, which names the GNU GPL."""
    text = ("                    GNU AFFERO GENERAL PUBLIC LICENSE\n"
            "                       Version 3, 19 November 2007\n\n"
            " Copyright (C) 2007 Free Software Foundation, Inc. <https://fsf.org/>\n"
            + "x\n" * 100 +
            "  13. Remote Network Interaction; Use with the GNU General Public "
            "License.\n")
    assert classify_license_text(text) == "AGPL-3.0"


def test_a_notice_decides_the_version_and_or_later():
    notice = ("This program is free software: you can redistribute it and/or modify\n"
              "it under the terms of the GNU Affero General Public License as\n"
              "published by the Free Software Foundation, either version 3 of the\n"
              "License, or (at your option) any later version.\n")
    assert classify_license_text(notice) == "AGPL-3.0-or-later"
    lesser = notice.replace("Affero", "Lesser")
    assert classify_license_text(lesser) == "LGPL-3.0-or-later"
    gpl2 = notice.replace("GNU Affero General", "GNU General").replace(
        "either version 3 of the\nLicense, or (at your option) any later version.",
        "version 2 of the License.")
    assert classify_license_text(gpl2) == "GPL-2.0"


def test_a_markdown_title_is_still_a_title():
    assert classify_license_text("# GNU General Public License\n\n"
                                 "## Version 3, 29 June 2007\n") == "GPL-3.0"


def test_a_gnu_phrase_in_prose_alone_decides_nothing():
    assert classify_license_text(
        "This README mentions the GNU General Public License version 3 in "
        "passing.") is None
