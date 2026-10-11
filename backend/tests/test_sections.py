from ingestion.layout import PageLayout
from ingestion.sections import build_sections


def lay(p, header):
    return PageLayout(pdf_page=p, width=1, height=1, header_title=header)


def test_chapters_nest_under_the_right_sub_book():
    headers = {
        1: None,  # title page of Fazail-e-Namaz
        2: "ফাযায়েলে নামায", 3: "ফাযায়েলে নামায",  # preface
        4: "প্রথম অধ্যায়", 5: "প্রথম অধ্যায়", 6: "দ্বিতীয় অধ্যায়", 7: "দ্বিতীয় অধ্যায়",
        8: None,  # title page of Fazail-e-Zikr
        9: "ফাযায়েলে যিকির", 10: "ফাযায়েলে যিকির",
        11: "প্রথম অধ্যায়", 12: "প্রথম অধ্যায়",
    }
    plan = build_sections([lay(p, h) for p, h in headers.items()])
    l1 = [(s.title, s.start_pdf_page, s.end_pdf_page) for s in plan.sections if s.level == 1]
    assert l1 == [("ফাযায়েলে নামায", 1, 7), ("ফাযায়েলে যিকির", 8, 12)]
    chapters = [(s.title, s.start_pdf_page, s.end_pdf_page, plan.sections[s.parent].title) for s in plan.sections if s.level == 2]
    assert chapters == [
        ("প্রথম অধ্যায়", 4, 5, "ফাযায়েলে নামায"),
        ("দ্বিতীয় অধ্যায়", 6, 7, "ফাযায়েলে নামায"),
        ("প্রথম অধ্যায়", 11, 12, "ফাযায়েলে যিকির"),
    ]


def test_ocr_noise_in_headers_is_absorbed():
    headers = {p: "ফাযায়েলে কুরআন" for p in range(1, 12)}
    headers[5] = "ফাযায়েলে কুরআ্ন"  # OCR slip
    headers[6] = "ফাযায়েল কুরআন"
    plan = build_sections([lay(p, h) for p, h in headers.items()])
    assert [(s.title, s.start_pdf_page, s.end_pdf_page) for s in plan.sections] == [("ফাযায়েলে কুরআন", 1, 11)]
