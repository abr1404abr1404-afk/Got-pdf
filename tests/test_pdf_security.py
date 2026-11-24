import unittest

import pymupdf

from pdf_security import unlock_pdf_bytes


class PdfSecurityTests(unittest.TestCase):
    def encrypted_pdf(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Password protected")
        data = doc.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner-test",
            user_pw="user-test",
            permissions=int(pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_COPY),
        )
        doc.close()
        return data

    def test_wrong_password_is_rejected(self):
        with self.assertRaises(ValueError):
            unlock_pdf_bytes(self.encrypted_pdf(), "wrong")

    def test_owner_password_produces_unencrypted_copy(self):
        result = unlock_pdf_bytes(self.encrypted_pdf(), "owner-test")
        with pymupdf.open(stream=result, filetype="pdf") as doc:
            self.assertFalse(doc.needs_pass)
            self.assertIn("Password protected", doc[0].get_text())

    def test_plain_pdf_is_returned_unchanged(self):
        doc = pymupdf.open()
        doc.new_page()
        data = doc.tobytes()
        doc.close()
        self.assertEqual(unlock_pdf_bytes(data, "unused"), data)


if __name__ == "__main__":
    unittest.main()
