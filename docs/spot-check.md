# Spot-check sheet: are the accuracy labels right?

The classifier's accuracy figures (`docs/evaluation.md`) were scored against labels that no person
has checked yet. This sheet lets a human check a sample of those labels in about 15 minutes. It is about the **labels only**;
the classifier's own output is deliberately not shown.

## How to do it

1. Read each case: the guest's "liked" text, the "disliked" text, and the labels the annotator assigned.
2. Decide whether a careful reader would tag the review the same way, by meaning (use the rules below).
3. In the last column write `yes`, or `no` plus which label is wrong or missing (for example `no: Staff (-) missing`).
4. Count the `yes` rows and fill in the tally at the bottom.
5. Send the tally back. Quote the agreement percentage next to the accuracy figures in `docs/evaluation.md` (a low value means those figures are less trustworthy).

## Rules for the topics

A label is a topic plus a direction: **(+)** the guest praises it, **(-)** the guest complains about it. Label by meaning,
not by which box the guest typed in (guests sometimes put complaints under "liked"). A review can have several labels.

| Topic | Covers |
|---|---|
| Cleanliness | Dirt, smells, hair, mould, pests, housekeeping, rubbish |
| Check-in | Arrival, door codes and keys, waiting to get in, self check-in, check-out |
| Staff | How people behaved: reception, hosts, managers, helpfulness, rudeness |
| Noise | Street, corridor or neighbour noise, thin walls, or praise for quiet |
| Facilities | Things the property provides: air conditioning, lift, kitchen, Wi-Fi, parking, towels, meals, number of bathrooms |
| Location | Position, walking distance, transport, nearby shops and venues |
| Room condition | The room itself: beds, mattress, furniture, state of repair, size, comfort |
| Value for money | Price against quality, "worth it", "overpriced" |

When two topics fit one sentence, the more specific one wins: "the lift was broken" is Facilities only, "hair in the
shower" is Cleanliness only. Ambiguous cases are marked in the note column. Sarcasm: label what the guest means, not the
literal words. Reviews in other languages are not part of this set.

## The 20 cases

Cases are every 5th entry of `tests/fixtures/real_gold_labels.json` (index 0, 5, 10, ... 95), so the selection is
reproducible. Source: real, anonymised public reviews; e-mail addresses and phone numbers are masked.

| # | Case id | Liked | Disliked | Annotator's labels | Annotator's note | Agree? (yes / no / which label is wrong) |
|---|---|---|---|---|---|---|
| 1 | `real_cd696c912d76` (index 0) | the Darling harbor view | cleaning, food, kitchen, general maintenance, few bathroom/toilet | Room condition (+)<br>Cleanliness (-)<br>Facilities (-)<br>Room condition (-) |  |  |
| 2 | `real_dff2a82d7552` (index 5) | I always book one night in a hostel before reserving it for a longer period. This hostel exceeded my expectations, so I extended my stay for two weeks. It has a convenient location, friendly staff, and the area was kept clean throughout my stay. | Unfortunately, there were some drunk and rude visitors, and since there’s no staff on-site at night, other guests had to deal with them on their own. | Location (+)<br>Staff (+)<br>Cleanliness (+)<br>Staff (-) |  |  |
| 3 | `real_119af5b2635f` (index 10) | it's tidy and snug, with a welcoming staff. the location in potts point couldn't be better, surrounded by numerous cafes and eateries. | *(empty)* | Staff (+)<br>Location (+) | 'tidy' not tagged |  |
| 4 | `real_a3a14c1f2fbb` (index 15) | The location was okay (if a little dodgy looking from the outside) and the privacy curtains around the bed were a nice touch. | The bathrooms were horrendous- there were 2 toilets and 3 showers for all of the rooms and only 2 doors actually locked. There was one sink with no soap dispenser and not even any paper towels to dry your hands. The photos are also obviously taken years ago when it was first renovated as it was not an accurate representation of what it looks like now.   They also have an app check-in 'to make things easier', but this didn't work. I had to email to ask what my rooms was (despite providing the extensive information required beforehand), then was initially given the wrong room number to go with the code I was provided. The staff did quickly rectify this (which was a positive), but it definitely didn't enhance my stay and I was not the only one with this issue. | Location (+)<br>Room condition (+)<br>Facilities (-)<br>Check-in (-)<br>Staff (+) |  |  |
| 5 | `real_2a810cd9e4dc` (index 20) | I liked the remote / zoom concierge I have never seen that before. I liked that ALL staff were very polite friendly hard working and respectful. I liked the firm comfortable mattress. I liked the bed curtains. I liked the on-site washing machine (free, including hot water if you want), and the on-site dryer ($4 per load, tap to pay). I liked the door code devices. I liked that breakfast and dinner are included. I liked the hot water in the shower. I liked the clean functional toilets including extras down in the backyard for more privacy and space. | A couple of the door code devices may need repair / replacing. Some of the patrons were disgusting how they treated the kitchen leaving huge cooking messes for staff to clean up, do they not understand over time that might lead to an increase in accommodation coat for everyone, if staff are required to work longer to clean up extra messes. Some patrons were selfish in how they were not quiet during sleep time. Towels a little pricey at $15, for that i can purchase my own. The wooden balustrades could benefit from repair and daily wipe down as we all relied on them to go up and down the steep stairs everyday. | Staff (+)<br>Room condition (+)<br>Facilities (+)<br>Check-in (+)<br>Cleanliness (+)<br>Check-in (-)<br>Cleanliness (-)<br>Noise (-)<br>Facilities (-)<br>Room condition (-) |  |  |
| 6 | `real_52b1e14eca25` (index 25) | I'd definitely choose to stay at this hostel again for my vacation. | *(empty)* | *(no labels)* |  |  |
| 7 | `real_d78efae43290` (index 30) | Best Location  high security  reasonable free  breakfast  Did not have free Dinner | No face-to-face contact with the administration or staff | Location (+)<br>Facilities (+)<br>Facilities (-)<br>Staff (-) | 'did not have free dinner' in liked box; both F polarities |  |
| 8 | `real_1b0b1ea88d19` (index 35) | Being close to the city and having delicious dineer every night | I think they can save a lot of money in water bills and electricity if they fix the taps and toilets cistern leaks | Location (+)<br>Facilities (+)<br>Room condition (-) |  |  |
| 9 | `real_deb22db49dc5` (index 40) | clean rooms, friendly staff, great location | *(empty)* | Cleanliness (+)<br>Staff (+)<br>Location (+) |  |  |
| 10 | `real_188903a6aa6b` (index 45) | The beds are comfy | You have to do the check in online because nobody is attending the hostel, I had the wait like 1 hour to do it. | Room condition (+)<br>Check-in (-) |  |  |
| 11 | `real_342f10399810` (index 50) | The hostel is super clean and safe with all the locks (outside the main door as well as outside the room door). Even if the staff is not physical present, it’s always available through the WhatsApp number, they helped me a lot with the self check in operations. | *(empty)* | Cleanliness (+)<br>Staff (+)<br>Check-in (+) |  |  |
| 12 | `real_b08b4201c72b` (index 55) | Staff were kind and helpful. | Mould on walls, noisy from street and other occupants slamming doors and putting in PIN codes. No practical place to put clothes/toiletries in bathroom while showering (only place is on toilet lid). | Staff (+)<br>Cleanliness (-)<br>Noise (-)<br>Facilities (-) |  |  |
| 13 | `real_7152ad6696ad` (index 60) | I liked the privacy curtains on the bunks | The online check in process has many flaws took me forever to get my code. The complimentary breakfast and dinner service is like a war zone trying to get to the food etc The bathrooms were never clean when I used them hairs everywhere, dirty shower floors and on my floor there was only 2 bathrooms available | Room condition (+)<br>Check-in (-)<br>Facilities (-)<br>Cleanliness (-) |  |  |
| 14 | `real_d189fb149e0a` (index 65) | breakfast was simple but a good way to start the day, and I noticed the new management is making improvements across the board; their dedication to enhancing the guest experience is inspiring. | *(empty)* | Facilities (+) |  |  |
| 15 | `real_160c20da9124` (index 70) | the kitchen facilities were nice to cook in, the place is pretty quiet and decent, i enjoy to walk so walking around the property was also great to do | *(empty)* | Facilities (+)<br>Noise (+)<br>Location (+) |  |  |
| 16 | `real_682d57bc349a` (index 75) | Staff gave all the needed information to check in and get into the room. It was easy to navigate how to get in to our room. | The shower was really dirty and needs a good clean, it also needed mat for the shower and it didnt come with one.  Same with the floor, it needs a decent mop. Our feet were black after getting out the shower and walking around the room. The toilet paper holder was broken, that needed to be fixed and maybe a hand towel and soap for the sink aswell. | Check-in (+)<br>Staff (+)<br>Cleanliness (-)<br>Facilities (-)<br>Room condition (-) |  |  |
| 17 | `real_214152a37175` (index 80) | Great location | Furnishings in dining is quite old. | Location (+)<br>Room condition (-) |  |  |
| 18 | `real_aa730ebbd230` (index 85) | It was comfortable and close to the stadium.. staff was very nice and accommodating. | *(empty)* | Room condition (+)<br>Location (+)<br>Staff (+) |  |  |
| 19 | `real_86be75f8e32e` (index 90) | GOING OUT THE DOOR. | NO AIR CONDITIONING, NO CUPS, NO MILK AND THEY DID NOT CARE | Facilities (-)<br>Staff (-) | liked 'GOING OUT THE DOOR' sarcastic, not labeled |  |
| 20 | `real_38940cc3f35b` (index 95) | + the room had a cozy setup  + the staff were happy to help with any charging needs. I was told they’re working on adding more outlets to make things even more convenient for guests. | *(empty)* | Room condition (+)<br>Staff (+) |  |  |

## Tally

| | |
|---|---|
| Cases checked (A) | 20 |
| Cases marked `yes` (B) | ______ |
| Cases marked `no` (C) | ______ |

**Agreement % = B / A x 100** (for example 17 yes out of 20 = 17 / 20 x 100 = 85%).

A case counts as `yes` only if every label is right and none is missing. Write any pattern you notice (for example
"complaints in the liked box are labelled positive") here: ____________________________________________
