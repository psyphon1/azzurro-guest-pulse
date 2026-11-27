# Topic classifier evaluation

Method `keywords` (`insights/classify.py`, `insights/topics.py`), classifier revision 3.

There are two evaluations. **The one on real reviews (first) is the one to trust.** The self-labelled set (appendix) is
kept as a regression check because it is optimistic.

## 1. Real reviews, labelled independently (100 cases)

**Sample.** 100 real English reviews that have written text, drawn at random (seed 7, `scripts/make_gold_sample.py`),
33 or 34 from each of Olympic Paddington, Potts Point and Darling Harbour (Central Sydney had no data yet). E-mail
addresses and phone numbers were masked and no reviewer identity is present. Reviews in other languages are excluded
because the keyword method is English only (about 20% of reviews).

**Labels.** Written by a separate annotator that never saw the classifier's code or output, following a fixed written
rule: label what a careful reader would tag, by meaning rather than by which box the guest typed in. The annotator is
an AI model, not a person, so these labels are an independent opinion, not ground truth. A human should spot-check
a sample before anyone quotes the numbers externally. The file is `tests/fixtures/real_gold_labels.json`
(`note` fields mark ambiguous cases and guests who used the wrong box).

**Split.** To avoid fooling ourselves, the first 50 cases are the **dev half** (keywords were tuned by looking at its
mistakes) and the last 50 are the **held-out test half** (never inspected while tuning, only scored).
Scores below count a prediction as correct only if topic and polarity both match, per review.

### Result on the held-out test half

| | Before tuning | After tuning |
|---|---|---|
| Precision | 0.79 | **0.84** |
| Recall | 0.72 | **0.76** |
| F1 | 0.75 | **0.80** |

After tuning, per topic on the held-out half:

```
topic             TP  FP  FN  precision  recall     F1
cleanliness       18   2   2       0.90    0.90   0.90
check_in          10   3   5       0.77    0.67   0.71
staff             19   3   8       0.86    0.70   0.78
noise              7   1   1       0.88    0.88   0.88
facilities        17   3   7       0.85    0.71   0.77
location          19   0   3       1.00    0.86   0.93
room_condition    12   6   7       0.67    0.63   0.65
value              3   2   0       0.60    1.00   0.75
OVERALL          105  20  33       0.84    0.76   0.80
```

The dev half went from F1 0.89 to 0.92. That gain is partly memorisation, which is why it is not the headline.
The held-out gain is the honest one. Small topics (value, noise) have very few cases, so their percentages move a lot
on one review.

### What was changed (all derived from dev-half mistakes)

- Meals (breakfast, lunch, dinner, food) and bathroom amenities or availability ("not enough toilets", "no mirror")
  now count as **facilities**. Bare "shower" and "toilet" no longer mean **room condition**, because "not enough showers"
  is a facility problem; "the shower was broken" is still caught through "broken".
- "Spacious", "roomy" and "cosy" count as room condition praise.
- A bare mention of staff, reception or service inside a *complaint* only counts as a **staff** complaint if the clause
  also says something negative. "...which I did inform the virtual receptionist about" is a cleanliness complaint, not
  a staff one. Real staff complaints ("receptionist was rude", "no staff on site", "verbally assaulted by staff") are kept
  and are covered by tests.

### Where it is still weak (held-out half)

- **Room condition** (precision 0.67, recall 0.63): the topic overlaps with facilities and cleanliness, and the labeller
  and the keywords draw the line in different places for bathrooms, beds and "comfortable".
- **Check-in** (recall 0.67): guests describe it indirectly ("had to wait for someone", "couldn't get in") and
  "didn't have to worry about check-in" is read as negated.
- **Staff** (recall 0.70) and **facilities** (recall 0.71): many complaints use words not in the lists.
- Sarcasm, complaints typed into the "liked" box, and non-English text are not handled (see README).

### How to reproduce

```
python scripts/make_gold_sample.py --db data/reviews.db --n 100 --seed 7 --out data/raw/gold_sample.json
python scripts/evaluate_classifier.py tests/fixtures/real_gold_labels.json --split test
python scripts/evaluate_classifier.py tests/fixtures/real_gold_labels.json --split dev
```

Caveats to keep in mind: 100 reviews, three hotels, English only, one annotator, and a held-out half of only 50 cases.
Treat the numbers as "roughly 0.8 F1, noticeably weaker on room condition", not as a precise measurement.

## Appendix: the earlier self-labelled set (49 cases)

Written and labelled by the classifier's own author (5 real anonymised reviews plus 44 invented cases), so it flatters the
classifier. After tuning it scores precision 0.90, recall 1.00, F1 0.95 (it scored 0.87 / 1.00 / 0.93 before), which at
least shows the tuning did not break the cases that were already right. Original notes follow.


Taxonomy version `1`, method `keywords` (`insights/classify.py`, `insights/topics.py`).
Reproduce with `python scripts/evaluate_classifier.py` (reads `tests/fixtures/gold_labels.json`).

## Method

- **Gold set:** 49 cases. 5 are the real anonymised Booking.com reviews in
  `tests/fixtures/olympic_reviewlist_page1.json`, labelled by hand from the `liked` / `disliked` text.
  44 are short hand-written cases covering negation, mixed topics, multiple topics per sentence,
  sarcasm, misplaced text, empty / missing text, and sentences with no topic at all.
- **Unit of scoring:** a review-level `(topic, polarity)` pair. A prediction is a true positive only if
  both topic and polarity match the gold label. One tag per pair per review, as in the table contract.
- **Only `liked` and `disliked` are classified.** The review title is not (the contract signature takes
  two texts). Example: the title of real review 2, "...expensive side for what you got", carries a
  value complaint that is therefore not tagged, and the gold labels do not expect it.
- **Labelling rule:** label what a careful human reader would tag, not what the keywords happen to hit.
  So "The lift was broken" is `facilities` only, and "Hair in the shower" is `cleanliness` only.

## Results (pasted from the script)

```
Gold cases: 49

topic             TP  FP  FN  precision  recall     F1
cleanliness       10   1   0       0.91    1.00   0.95
check_in           6   0   0       1.00    1.00   1.00
staff              9   2   0       0.82    1.00   0.90
noise              8   1   0       0.89    1.00   0.94
facilities        10   0   0       1.00    1.00   1.00
location           9   0   0       1.00    1.00   1.00
room_condition     5   4   0       0.56    1.00   0.71
value              5   1   0       0.83    1.00   0.91
OVERALL           62   9   0       0.87    1.00   0.93

Misses and false positives (9):
  false_positive  real_1_b5dd03: staff/negative  <- 'The lobby looked like an unwelcoming storage room.'
  false_positive  real_2_cdea28: staff/negative  <- 'There was a kettle, but no cups and cockroaches, which I did inform the virtual receptionist about.'
  false_positive  lift_broken_is_facilities_only: room_condition/negative  <- 'The lift was broken.'
  false_positive  hair_and_mould: room_condition/negative  <- 'Hair in the shower and mould on the ceiling.'
  false_positive  sarcasm_liked_cockroaches: cleanliness/positive  <- 'Lovely cockroaches, really enjoyed sharing my room.'
  false_positive  three_topics_one_sentence: room_condition/negative  <- 'The shower was dirty, the staff ignored us and it was too noisy.'
  false_positive  cheap_but_lumpy_mattress: value/negative  <- 'Cheap but you get what you pay for, the mattress was lumpy.'
  false_positive  rough_street_is_not_noise: noise/negative  <- 'The street outside is a bit rough.'
  false_positive  multi_sentence_mixed: room_condition/negative  <- 'The air conditioning was broken.'
```

## Failure modes found

1. **Keyword overlap between topics (most false positives).** `broken`, `shower`, `toilet` are
   room-condition words, so "the lift was broken" or "dirty shower" also tag `room_condition`. The
   classifier cannot tell which topic the sentence is *about*. This is why `room_condition` precision is
   the weakest (0.56). Mitigation if it matters: drop bare `broken` / `shower` and rely on phrases, or
   let a more specific topic in the same sentence suppress the generic one.
2. **Staff words describing things, not people.** "unwelcoming storage room" and "virtual receptionist"
   (a guest *reporting* a problem to the receptionist, not complaining about them) tag `staff`.
3. **Sarcasm.** "Lovely cockroaches, really enjoyed sharing my room" in `liked` is tagged
   `cleanliness` positive. Not handled by design (no sentiment model); documented limitation. The real
   sarcastic case "GOING OUT THE DOOR." produces no tag only because no keyword matches.
4. **Ambiguous single words.** `street` (noise), `cheap` (value, praise or insult?). Both produced a
   false positive here.
5. **Complaint inside a praise word.** "Cheap but you get what you pay for" is not a value complaint on
   the keywords alone.

What works: negation (`not dirty`, `no issues with noise`, `nothing to complain about`, `not clean` in
`liked`), absence of a facility treated as a complaint (`no air conditioning`), clause boundaries
stopping negation leaking, and `walked past` no longer counting as a location mention.

## Honest caveats

- **The gold set is small (49 cases) and labelled by the same person who wrote the keywords.** The
  numbers are optimistic. Recall of 1.00 is a symptom of that: the hand-written cases use vocabulary
  the keyword lists already contain. The 5 real reviews were also in view while the keywords were
  written (for example `did not care`, `robo check in`, `cockroaches`), so they are training data, not
  a held-out test.
- Real guests write messier text (typos, other languages, slang, long run-on sentences). Expect real
  recall to be clearly lower than 1.00, and precision for `room_condition` and `staff` to stay weak.
- A 49-case set cannot support per-topic claims; several topics have fewer than 10 positive examples.
- The `language` column is not used: non-English reviews will mostly get no tags.

## Plan to get honest numbers (written before the real evaluation; it has since been done, see section 1: the real labels are in `tests/fixtures/real_gold_labels.json`)

1. Once the scraper has run, sample about 100 real reviews across all four properties (stratified by
   rating band, include some non-English and some very short ones).
2. Label them blind (without looking at the classifier output), ideally by someone other than the
   keyword author, using the same labelling rule as above. Append to a second file
   (`tests/fixtures/gold_real.json`) so the original cases stay as a regression set.
3. Run `python scripts/evaluate_classifier.py tests/fixtures/gold_real.json`, replace the numbers in this
   document, and treat them as the reportable result.
4. Only then tune keywords (bumping `TAXONOMY_VERSION`, which makes the pipeline re-tag everything) and
   re-check on a fresh sample so we do not overfit to the 100.
5. If keyword precision stays too low for `room_condition` / `staff`, add the LLM method
   (`method = 'llm'`) behind the same table.
