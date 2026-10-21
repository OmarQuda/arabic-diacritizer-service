import pytest

from app.validation import DIACRITICS, count_changed, strip_diacritics, validate


@pytest.mark.parametrize("source,output", [
    ("ذهب الولد إلى المدرسة", "ذَهَبَ الْوَلَدُ إِلَى الْمَدْرَسَةِ"),
    ("كتاب", "كِتَابٌ"), ("السَلام", "السَّلَامُ"), ("هذا", "هٰذا"),
    ("قـلم", "قَـلَمٌ"), ("بيت،\nقلم!", "بَيْتٌ،\nقَلَمٌ!"),
    ("abc 123", "abc 123"), ("**قلم**", "**قَلَمٌ**"),
])
def test_valid(source, output):
    assert validate(source, output).valid


@pytest.mark.parametrize("output,reason", [
    ("", "empty"), (" \n", "empty"), ("ذهب الولد إضافي", "added_words"),
    ("ذهب", "removed_words"), ("ذهب البنت", "changed_letters"),
    ("ذهب  الولد", "changed_letters"), ("ذهب الولد!", "changed_letters"),
    ("```arabic\nذهب الولد\n```", "markdown"), ("**ذهب الولد**", "markdown"),
    ("# ذهب الولد", "markdown"), ('{"text":"ذهب الولد"}', "json"),
    ("*ذهب الولد*", "markdown"), ("- ذهب الولد", "markdown"),
    ("> ذهب الولد", "markdown"), ("~~~\nذهب الولد\n~~~", "markdown"),
    ('["ذهب الولد"]', "json"), ("The boy", "changed_letters"),
])
def test_reasons(output, reason):
    verdict = validate("ذهب الولد", output)
    assert not verdict.valid and verdict.reason == reason and verdict.detail


@pytest.mark.parametrize("mark", sorted(DIACRITICS))
def test_every_supported_mark(mark):
    assert strip_diacritics("ب" + mark) == "ب"


@pytest.mark.parametrize("source,output", [("قلم", "قـلم"), ("أمل", "امل"), ("أ", "أ"), ("قلم", "قلم\u0653")])
def test_unsupported_changes_rejected(source, output):
    assert validate(source, output).reason == "changed_letters"


@pytest.mark.parametrize("before,after,count", [("قلم", "قَلَمٌ", 3), ("بَ", "بُ", 1), ("بَّ", "بَ", 1), ("بَّ", "بَّ", 0)])
def test_diacritic_distance(before, after, count):
    assert count_changed(before, after) == count
