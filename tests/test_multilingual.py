"""Phase 1 tagging fixes: languages other than English, safety, empty answers, field-aware polarity, cross-fires.

The texts marked "real" are copied from reviews in the collected data."""
import pytest

from insights.classify import (
    KeywordClassifier,
    TopicClassifier,
    classify_review,
    is_low_signal,
)
from insights.language import analysis_language

FRENCH_COCKROACHES = (  # real, review e70fb7a3103f6b92, score 1/10, disliked box
    "L’auberge est extrêmement sale et insalubre. Il y a des cafards dans les chambres (dont un qui m'a couru "
    "dessus pendant la nuit), ainsi que des insectes et de la moisissure partout dans les salles de bain. "
    "La cuisine est également dans un état déplorable, avec de la nourriture en train de pourrir.\n"
    "En plus du manque total d’hygiène, la sécurité laisse également à désirer : des multiprises sont branchées "
    "les unes sur les autres, créant un risque électrique et un potentiel danger d’incendie.\n"
    "Un établissement aussi sale que dangereux.")


def tags(liked, disliked, language="en"):
    return {(t.topic, t.polarity) for t in classify_review(liked, disliked, language)}


# --- a. other languages --------------------------------------------------------------------------------------------
def test_the_french_cockroach_review_is_now_tagged_with_cleanliness_and_safety():
    got = tags(None, FRENCH_COCKROACHES, "fr")
    assert ("cleanliness", "negative") in got
    assert ("safety", "negative") in got


@pytest.mark.parametrize("lang,liked,disliked,expected", [
    ("es", "El personal muy amable y la ubicación perfecta.", "La habitación estaba sucia y había mucho ruido.",
     {("staff", "positive"), ("location", "positive"), ("cleanliness", "negative"), ("noise", "negative")}),
    ("de", "Sehr freundliches Personal, gute Lage.", "Das Zimmer war schmutzig und es war laut.",
     {("staff", "positive"), ("location", "positive"), ("cleanliness", "negative"), ("noise", "negative")}),
    ("it", "Posizione ottima, personale gentile.", "Bagno sporco e materasso scomodo.",
     {("location", "positive"), ("staff", "positive"), ("cleanliness", "negative"), ("room_condition", "negative")}),
    ("pt", "Localização excelente e funcionários simpáticos.", "Quarto sujo e muito barulho.",
     {("location", "positive"), ("staff", "positive"), ("cleanliness", "negative"), ("noise", "negative")}),
    ("fr", "Personnel très sympathique, bien situé, à deux pas de la gare.", "Chambre sale, trop cher.",
     {("staff", "positive"), ("location", "positive"), ("cleanliness", "negative"), ("value", "negative")}),
])
def test_each_supported_language_gets_tags(lang, liked, disliked, expected):
    assert expected <= tags(liked, disliked, lang)


@pytest.mark.parametrize("lang,disliked", [
    ("fr", "La chambre n'était pas sale."),
    ("es", "La habitación no estaba sucia."),
    ("de", "Das Zimmer war nicht schmutzig."),
    ("it", "La camera non era sporca."),
    ("pt", "O quarto não estava sujo."),
])
def test_negation_works_in_each_language(lang, disliked):
    assert ("cleanliness", "negative") not in tags(None, disliked, lang)


def test_foreign_words_do_not_fire_in_english_and_english_words_not_in_french():
    assert tags(None, "There was a sale downstairs.", "en") == set()   # "sale" is French for dirty, not English
    assert ("staff", "negative") not in tags(None, "personal opinion only", "en")


@pytest.mark.parametrize("code,text,expected", [
    ("en", "anything", "en"), ("en-gb", "x", "en"), ("fr", "texte", "fr"), ("es", "texto", "es"),
    ("xa", "la habitación", "es"), ("xm", "texto", "es"), ("de", "Text", "de"), ("it", "testo", "it"),
    ("pt", "texto", "pt"), ("xb", "o quarto", "pt"), ("pt-br", "texto", "pt"),
    ("ja", "部屋はきれい", None), ("zh", "很好", None), ("xt", "很好", None),
    ("xu", "The room was clean and the staff were great", "en"), (None, "", None),
])
def test_analysis_language_routing(code, text, expected):
    assert analysis_language(code, text) == expected


def test_unsupported_language_gets_no_tags():
    assert tags(None, "部屋が汚い", None) == set()


# --- b. safety -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("disliked", [
    "There were cockroaches in the kitchen.", "Bed bugs in the dorm.", "Black mould on the ceiling.",
    "Saw a rat in the hallway.", "Exposed electrical wires near the bed, a fire hazard.",
    "My phone was stolen from the room.", "I felt unsafe at night.",
])
def test_safety_complaints_in_english(disliked):
    assert ("safety", "negative") in tags(None, disliked)


@pytest.mark.parametrize("lang,disliked", [
    ("es", "Había cucarachas y moho en el baño."), ("es", "Me robaron el móvil."),
    ("de", "Kakerlaken und Schimmel im Bad."), ("it", "Scarafaggi in camera e muffa ovunque."),
    ("pt", "Havia baratas e mofo no banheiro."), ("fr", "Des punaises de lit partout."),
])
def test_safety_complaints_in_other_languages(lang, disliked):
    assert ("safety", "negative") in tags(None, disliked, lang)


@pytest.mark.parametrize("disliked", [
    "The fire exit was blocked by bags.", "The fire alarm went off at 3am.", "No fireplace in the lounge.",
    "The band stole the show downstairs.", "Bring your own electrical adaptor.",
])
def test_safety_false_positives(disliked):
    assert ("safety", "negative") not in tags(None, disliked)


def test_safety_never_appears_as_praise():
    assert not any(t[0] == "safety" for t in tags("Felt safe, no bugs, no cockroaches at all", None))
    assert not any(t[0] == "safety" for t in tags("Loved it even with one cockroach", None))


# --- c. empty answers ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "nothing", "Nothing.", "none", "N/A", "n/a", "na", "-", "no complaints", "Nothing to dislike",
    "nothing really", "Nothing at all!", "everything", "all good", "rien", "Rien à signaler", "nada", "Nichts",
    "niente", "nada a reclamar", "  NOTHING  ",
])
def test_low_signal_answers(text):
    assert is_low_signal(text)


@pytest.mark.parametrize("text", ["nothing was clean", "The bed", "no hot water", "Everything was dirty"])
def test_real_text_is_not_low_signal(text):
    assert not is_low_signal(text)


@pytest.mark.parametrize("text", ["nothing", "none", "n/a", "no complaints", "nothing to dislike", "everything"])
def test_low_signal_answers_yield_no_tags_in_either_box(text):
    assert tags(text, text) == set()


# --- d. field-aware polarity and cross-fires -----------------------------------------------------------------------
def test_liked_box_only_praise_and_disliked_box_only_complaints():
    got = tags("The room was dirty but the staff were lovely", "Great location though the bed was bad")
    assert all(p == "positive" for t, p in got if (t, p) in tags("The room was dirty but the staff were lovely", None))
    assert all(p == "negative" for _, p in tags(None, "Great location though the bed was bad"))


def test_real_window_review_does_not_praise_room_condition():  # real, db7af74897e78b71, 3/10
    got = tags("I liked how close it was to Allianz stadium. I liked the window opened.", None)
    assert ("room_condition", "positive") not in got
    assert ("location", "positive") in got


def test_window_complaint_still_counts():
    assert ("room_condition", "negative") in tags(None, "The window didnt have flyscreen and would not close.")


def test_real_host_and_free_dinner_is_staff_not_facilities():  # real, 3489fb6995453723, 9/10
    got = tags("to quite honestly and great host and free dinner", "nothing")
    assert ("staff", "positive") in got
    assert ("facilities", "positive") not in got
    assert not any(p == "negative" for _, p in got)


def test_real_dirty_shower_room_on_a_ten_keeps_the_complaint():  # real, ca96e46438ff33bd, 10/10
    assert ("cleanliness", "negative") in tags("This is a good place", "Dirty shower room")


# --- e. extension point --------------------------------------------------------------------------------------------
def test_keyword_classifier_satisfies_the_interface():
    clf: TopicClassifier = KeywordClassifier()
    assert clf.method == "keywords"
    assert {(t.topic, t.polarity) for t in clf.classify(None, "Dirty room", "en")} == {("cleanliness", "negative")}


def test_comment_counts_separate_not_english_from_not_analysed():
    from datetime import date

    import pandas as pd

    from insights import metrics
    df = pd.DataFrame([
        {"review_key": k, "property": "olympic-paddington", "rating": 2.0, "review_date": "2026-03-03",
         "liked": None, "disliked": d, "language": lang}
        for k, d, lang in [("a", "dirty", "en"), ("b", "sale", "fr"), ("c", "sucio", "es"), ("d", "汚い", "ja")]])
    c = metrics.comment_counts(df, date(2026, 3, 2), date(2026, 3, 8))
    assert (c.n_with_comment, c.n_non_english, c.n_not_analysed) == (4, 3, 1)


def test_safety_insight_is_pinned_first_with_an_action():
    from datetime import date

    import pandas as pd

    from insights import metrics
    rows = [{"review_key": f"r{i}", "property": "olympic-paddington", "rating": 9.0, "review_date": "2026-03-03",
             "liked": "great", "disliked": None, "language": "en", "host_reply": None} for i in range(6)]
    rows.append({"review_key": "bad", "property": "olympic-paddington", "rating": 2.0, "review_date": "2026-03-04",
                 "liked": None, "disliked": "cockroaches", "language": "en", "host_reply": None})
    df = pd.DataFrame(rows)
    topics = pd.DataFrame([{"review_key": "bad", "topic": "safety", "polarity": "negative", "evidence": "cockroaches"},
                           {"review_key": "bad", "topic": "cleanliness", "polarity": "negative", "evidence": "x"}])
    out = metrics.generate_insights(df, topics, date(2026, 3, 2))
    assert out[0].action == {"safety": True} and out[0].kind == "alert"
    assert "safety issue" in out[0].text and "1 review" in out[0].text
    unreplied = [i for i in out if i.action == {"neg": True, "noreply": True}]
    assert unreplied, [i.text for i in out]


def test_no_safety_insight_without_safety_tags():
    from datetime import date

    import pandas as pd

    from insights import metrics
    df = pd.DataFrame([{"review_key": "a", "property": "olympic-paddington", "rating": 9.0,
                        "review_date": "2026-03-03", "liked": "great", "disliked": None, "language": "en"}])
    out = metrics.generate_insights(df, pd.DataFrame(columns=["review_key", "topic", "polarity", "evidence"]),
                                    date(2026, 3, 2))
    assert not any((i.action or {}).get("safety") for i in out)


def test_spanish_rip_off_idiom_is_value_not_theft():
    assert ("safety", "negative") not in tags(None, "Un robo este lugar", "es")
