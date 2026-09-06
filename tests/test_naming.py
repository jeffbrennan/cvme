from pathlib import Path

import pytest

from cvme.generate.naming import role_title, token
from cvme.hunt.layout import next_round


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            "Data Engineer III - Digital and Technology Partners - Hybrid/Remote",
            "data_engineer",
        ),
        ("Specialist Data Engineer", "data_engineer"),
        ("Senior Data Engineer", "senior_data_engineer"),
        ("Staff Data Engineer (Remote)", "staff_data_engineer"),
        ("Sr. Data Engineer, Platform", "senior_data_engineer"),
        ("Principal Software Engineer 2 | New York", "principal_software_engineer"),
        ("Lead Data Engineer IV", "lead_data_engineer"),
        ("Data Engineer - Req 12345", "data_engineer"),
    ],
)
def test_normalized_role_title(title: str, expected: str) -> None:
    assert role_title(title) == expected


def test_name_cannot_create_a_path() -> None:
    assert token("Jeff Brennan") == "jeff_brennan"
    assert token("../../José O\u2019Brien") == "jose_obrien"


def test_version_directories_continue_legacy_rounds(tmp_path: Path) -> None:
    (tmp_path / "cv2.md").write_text("old draft")
    assert next_round(tmp_path, ["cv"]) == 3
    (tmp_path / "v3").mkdir()
    assert next_round(tmp_path, ["cv"]) == 4
