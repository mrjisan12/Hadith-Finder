from ingestion.page_numbers import infer_page_numbers


def run(detected, overrides=None):
    return {r.pdf_page: r for r in infer_page_numbers(detected, overrides)}


def test_drifting_offset_is_followed_not_assumed():
    # offset +2 for pages 1-10, then an unnumbered plate at 11, offset +2 again after (printed 13 at pdf 12 ... )
    detected = {p: p + 2 for p in range(1, 11)}
    detected[11] = None  # plate
    detected.update({p: p + 1 for p in range(12, 20)})  # numbering continues 13, 14, ...
    r = run(detected)
    assert r[5].printed == 7 and r[5].source == "ocr"
    assert r[12].printed == 13
    # 10 -> 12 printed, 12 -> 13 printed; one page in between with no number available: must NOT be guessed
    assert r[11].printed is None and r[11].source == "unknown"


def test_single_misread_is_corrected_by_neighbours():
    detected = {p: p + 3 for p in range(1, 21)}
    detected[10] = 16  # ১৩ misread as ১৬
    r = run(detected)
    assert r[10].printed == 13
    assert r[10].source == "inferred" and r[10].flag == "conflict"


def test_agreeing_pair_of_misreads_cannot_hijack_the_sequence():
    detected = {p: p + 3 for p in range(1, 41)}
    detected[20], detected[21] = 823, 824  # two consecutive consistent misreads (২৩/২৪ -> ৮২৩/৮২৪)
    r = run(detected)
    assert r[20].printed == 23 and r[21].printed == 24
    assert all(r[p].printed == p + 3 for p in range(1, 41))


def test_missing_detection_filled_when_unambiguous():
    detected = {p: p + 7 for p in range(1, 11)}
    detected[5] = None
    r = run(detected)
    assert r[5].printed == 12 and r[5].source == "inferred"


def test_unverified_edges_are_not_extrapolated():
    detected = {1: None, 2: None, 3: 5, 4: 6, 5: 7}
    r = run(detected)
    assert r[1].printed is None and r[2].printed is None
    assert r[3].printed == 5


def test_manual_override_wins():
    detected = {p: p + 3 for p in range(1, 11)}
    r = run(detected, {4: 99, 5: None, 6: "iv"})
    assert r[4].printed == 99 and r[4].source == "manual"
    assert r[5].printed is None and r[5].source == "manual"
    assert r[6].printed is None and r[6].label == "iv"
