from insights.classify import TopicTag, classify_review
from insights.topics import TAXONOMY_VERSION, TOPICS


def pairs(tags):
    return {(t.topic, t.polarity) for t in tags}


# --- taxonomy ----------------------------------------------------------
def test_taxonomy_has_exactly_the_contract_topics():
    assert TAXONOMY_VERSION == "1"
    assert {k: t.label for k, t in TOPICS.items()} == {
        "cleanliness": "Cleanliness",
        "check_in": "Check-in experience",
        "staff": "Staff behaviour",
        "noise": "Noise",
        "facilities": "Facilities",
        "location": "Location",
        "room_condition": "Room condition",
        "value": "Value for money",
    }
    assert all(k == t.id and t.keywords for k, t in TOPICS.items())


# --- basic polarity and evidence --------------------------------------
def test_liked_text_gives_positive_and_disliked_gives_negative():
    tags = classify_review("Great location.", "The room was dirty.")
    assert pairs(tags) == {("location", "positive"), ("cleanliness", "negative")}


def test_tag_carries_exact_sentence_as_evidence_and_method():
    tags = classify_review(None, "Check in was fine. The shower was dirty and cold. Nothing else.")
    tag = next(t for t in tags if t.topic == "cleanliness")
    assert tag == TopicTag("cleanliness", "negative", "The shower was dirty and cold.", "keywords")


def test_none_and_empty_text_give_no_tags():
    assert classify_review(None, None) == []
    assert classify_review("", "   ") == []


def test_matching_is_case_insensitive():
    assert pairs(classify_review(None, "NO AIR CONDITIONING")) == {("facilities", "negative")}


def test_matching_uses_word_boundaries():
    # 'bed' inside 'embedded', 'fan' inside 'fantastic', 'hair' inside 'chairman'
    assert classify_review("An embedded fantastic chairman.", None) == []


def test_bare_door_does_not_match_door_code_keyword():
    assert classify_review("GOING OUT THE DOOR.", None) == []


def test_walked_past_is_not_a_location_mention():
    tags = classify_review(None, "It's a little noisy when people have walked past your room.")
    assert pairs(tags) == {("noise", "negative")}


# --- dedupe and multi-topic -------------------------------------------
def test_one_tag_per_topic_and_polarity_keeps_first_evidence():
    tags = classify_review(None, "The bathroom was dirty. The floor was grubby too.")
    clean = [t for t in tags if t.topic == "cleanliness"]
    assert len(clean) == 1
    assert clean[0].evidence == "The bathroom was dirty."


def test_one_sentence_can_tag_several_topics():
    tags = classify_review(None, "The kitchen was grubby and the lift was broken.")
    assert {"cleanliness", "facilities", "room_condition"} <= {t.topic for t in tags}


def test_same_topic_can_be_both_positive_and_negative():
    tags = classify_review("Lovely helpful staff.", "The receptionist was rude.")
    assert pairs(tags) == {("staff", "positive"), ("staff", "negative")}


# --- real-data vocabulary ---------------------------------------------
def test_real_vocabulary_is_recognised():
    cases = {
        "cleanliness": "There were cockroaches and a sewerage smell.",
        "check_in": "The robo check in was confusing.",
        "staff": "No staff on site.",
        "noise": "Thin walls and loud neighbours.",
        "facilities": "No cups, no milk and no air conditioning.",
        "location": "Close to Allianz Stadium and the station.",
        "room_condition": "The mattress was old and the room felt run down.",
        "value": "Overpriced for what you get.",
    }
    for topic, text in cases.items():
        assert (topic, "negative") in pairs(classify_review(None, text)), topic


# --- negation ---------------------------------------------------------
def test_negated_problem_in_disliked_gives_no_negative_tag():
    for text in ["The room was not dirty.", "It wasn't noisy at all.", "No issues with noise.",
                 "Nothing to complain about.", "No smell, no cockroaches.", "The staff were never rude.",
                 "Not at all dirty", "There was no noise."]:
        assert classify_review(None, text) == [], text


def test_all_clear_phrase_cancels_whole_clause_in_disliked():
    assert classify_review(None, "No complaints about the check in or the staff.") == []
    assert classify_review(None, "Can't fault the location.") == []


def test_all_clear_only_cancels_its_own_clause():
    tags = classify_review(None, "No issues with noise but the air conditioning was broken.")
    assert pairs(tags) == {("facilities", "negative"), ("room_condition", "negative")}


def test_negated_praise_in_liked_gives_no_positive_tag():
    for text in ["The room was not clean.", "Staff weren't helpful.", "It was not quiet."]:
        assert classify_review(text, None) == [], text


def test_negated_praise_in_disliked_is_still_a_complaint():
    assert pairs(classify_review(None, "The room was not clean.")) == {("cleanliness", "negative")}
    assert pairs(classify_review(None, "The staff weren't helpful.")) == {("staff", "negative")}
    assert pairs(classify_review(None, "Not close to the station.")) == {("location", "negative")}


def test_absence_of_a_facility_is_a_complaint_not_a_negation():
    assert pairs(classify_review(None, "No air conditioning, no cups, no milk.")) == {("facilities", "negative")}
    assert pairs(classify_review(None, "There was no wifi.")) == {("facilities", "negative")}


def test_negated_problem_in_liked_is_a_positive_mention():
    assert pairs(classify_review("No noise at all.", None)) == {("noise", "positive")}
    assert pairs(classify_review("Not dirty, no smell.", None)) == {("cleanliness", "positive")}


def test_negation_in_another_clause_does_not_leak():
    tags = classify_review(None, "It was not a long stay, but the room was dirty.")
    assert pairs(tags) == {("cleanliness", "negative")}


def test_did_not_have_a_facility_is_not_negation_of_the_facility():
    assert pairs(classify_review(None, "The room did not have air conditioning.")) == {("facilities", "negative")}


def test_curly_apostrophe_negation():
    assert classify_review(None, "It wasn’t dirty.") == []


# --- known limitation: sarcasm ---------------------------------------
def test_sarcasm_in_liked_is_not_detected_but_door_alone_is_not_a_tag():
    # Documented limitation: we do not try to detect sarcasm. This real case only works because
    # no keyword is present.
    assert classify_review("GOING OUT THE DOOR.", "NO AIR CONDITIONING") == [
        TopicTag("facilities", "negative", "NO AIR CONDITIONING", "keywords")
    ]


# --- evaluation script ------------------------------------------------
def _load_evaluator():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parent.parent / "scripts" / "evaluate_classifier.py"
    spec = importlib.util.spec_from_file_location("evaluate_classifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_evaluate_counts_tp_fp_fn_per_topic_and_overall():
    ev = _load_evaluator()
    cases = [
        {"id": "a", "liked": "Great location.", "disliked": "The room was dirty.",
         "expected": [["location", "positive"], ["cleanliness", "negative"]]},
        {"id": "b", "liked": None, "disliked": "Noisy.", "expected": [["staff", "negative"]]},
    ]

    report = ev.evaluate(cases)

    assert report.per_topic["location"].tp == 1
    assert (report.per_topic["noise"].fp, report.per_topic["staff"].fn) == (1, 1)
    assert report.overall.tp == 2 and report.overall.fp == 1 and report.overall.fn == 1
    assert report.overall.precision == 2 / 3 and report.overall.recall == 2 / 3
    assert [(m.case_id, m.kind, m.topic) for m in report.misses] == [
        ("b", "false_positive", "noise"), ("b", "false_negative", "staff")
    ]


def test_evaluate_scores_zero_division_as_zero():
    ev = _load_evaluator()
    assert ev.Counts().precision == 0.0 and ev.Counts().f1 == 0.0


def test_gold_file_is_well_formed_and_large_enough():
    import json
    from pathlib import Path

    cases = json.loads((Path(__file__).parent / "fixtures" / "gold_labels.json").read_text())
    assert len(cases) >= 30
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert set(c) >= {"id", "liked", "disliked", "expected"}
        for topic, polarity in c["expected"]:
            assert topic in TOPICS and polarity in ("positive", "negative")
