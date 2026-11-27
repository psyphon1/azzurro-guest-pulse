import pytest

from insights.language import is_english_like

ENGLISH = "The room was clean and the staff were friendly."
CHINESE = "鄰近國家博物館對我來說是一大好處！辦理入住手續也很順利"
FRENCH_WITH_ENGLISH_WORDS = "Le wifi est lent et la location est loin de la gare, pas de reception le soir."


@pytest.mark.parametrize("code", ["en", "en-GB", "EN", "en_US", " en "])
def test_english_codes_are_english_whatever_the_text(code):
    assert is_english_like(code, CHINESE) is True


@pytest.mark.parametrize("code", ["fr", "es", "zh", "de", "it", "ja", "ko", "ru", "ar", "pl", "pt", "da", "no"])
def test_other_recognised_codes_are_not_english_even_when_text_looks_english(code):
    assert is_english_like(code, ENGLISH) is False


@pytest.mark.parametrize("code", [None, "", "   "])
def test_missing_language_judged_by_text(code):
    assert is_english_like(code, ENGLISH) is True
    assert is_english_like(code, CHINESE) is False


def test_xu_with_english_text_is_english():
    assert is_english_like("xu", "The location Is perfect, close to the transportation and restaurants.") is True


def test_xt_with_chinese_text_is_not_english():
    assert is_english_like("xt", CHINESE) is False


@pytest.mark.parametrize("code,text", [
    ("xb", "Localização perfeita, o café da manhã e o jantar foram 10/10 e a equipe é simpática"),
    ("xa", "Ubicación perfecta! Desayuno muy rico, la cama es cómoda y el hostel está muy limpio"),
])
def test_other_x_codes_with_latin_non_english_text_are_not_english(code, text):
    assert is_english_like(code, text) is False


def test_french_text_carrying_english_words_is_not_english_by_text():
    # Pure ASCII-ish, contains "wifi" and "location" but no English stopword.
    assert is_english_like(None, FRENCH_WITH_ENGLISH_WORDS) is False
    assert is_english_like("xu", FRENCH_WITH_ENGLISH_WORDS) is False
    assert is_english_like("fr", FRENCH_WITH_ENGLISH_WORDS) is False


@pytest.mark.parametrize("texts", [(None,), ("",), ("   ",), (None, None), ()])
def test_no_text_and_no_language_is_not_english_like(texts):
    assert is_english_like(None, *texts) is False


def test_no_text_with_english_code_is_still_english():
    assert is_english_like("en", None, "") is True


def test_texts_are_combined_liked_and_disliked():
    assert is_english_like(None, None, ENGLISH) is True
    assert is_english_like(None, "Good", "The bed was hard") is True


def test_mixed_language_text_mostly_english_passes_mostly_foreign_fails():
    mostly_english = "The staff was lovely and the kitchen was big. 非常好"
    mostly_chinese = "鄰近國家博物館對我來說是一大好處，辦理入住手續也很順利，非常省事，我真的很感激 the end"
    assert is_english_like(None, mostly_english) is True
    assert is_english_like(None, mostly_chinese) is False


def test_non_string_text_is_ignored_not_raised():
    assert is_english_like(None, 123, ENGLISH) is True
    assert is_english_like(None, 123) is False
    assert is_english_like(5, ENGLISH) is True


def test_only_the_start_of_a_long_text_is_read_so_pipeline_and_dashboard_agree():
    long_english = ("The room was clean. " * 600)[:10_000]
    assert is_english_like(None, long_english + CHINESE * 5000) is True
