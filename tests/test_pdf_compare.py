import pymupdf
import pytest

from pdf_compare import compare_pdf_bytes


def make_pdf(lines):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "\n".join(lines))
    data = doc.tobytes()
    doc.close()
    return data


def test_compare_reports_added_and_removed_text_without_changing_source():
    original = make_pdf(["Alpha", "Keep"])
    revised = make_pdf(["Beta", "Keep", "New"])

    result = compare_pdf_bytes(original, revised)

    assert result["changed_pages"] == 1
    assert result["pages"][0]["status"] == "changed"
    assert "Beta" in result["pages"][0]["text"]["added_lines"]
    assert "Alpha" in result["pages"][0]["text"]["removed_lines"]
    assert "New" in result["pages"][0]["text"]["added_lines"]
    assert make_pdf(["Alpha", "Keep"]) == original


def test_compare_detects_added_and_removed_pages():
    one_page = make_pdf(["Page one"])
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Page one")
    page = doc.new_page()
    page.insert_text((72, 72), "Page two")
    two_pages = doc.tobytes()
    doc.close()

    result = compare_pdf_bytes(one_page, two_pages)

    assert result["revised_page_count"] == 2
    assert result["changed_pages"] == 1
    assert result["pages"][1]["status"] == "added"


@pytest.mark.parametrize("data,label", [(b"", "الأصلي"), (b"not pdf", "المعدّل")])
def test_compare_rejects_empty_or_invalid_pdf(data, label):
    with pytest.raises(ValueError):
        compare_pdf_bytes(data, make_pdf(["valid"])) if label == "الأصلي" else compare_pdf_bytes(make_pdf(["valid"]), data)
