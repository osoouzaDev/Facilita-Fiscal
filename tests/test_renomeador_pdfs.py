import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from renomeador_pdfs import (
    analyze_folder,
    apply_renames,
    extract_company_name_from_text,
    sanitize_filename,
)


SAMPLE_TEXT = """
MINISTÉRIO DA FAZENDA
INFORMAÇÕES DE APOIO PARA EMISSÃO DE CERTIDÃO
CNPJ: 49.084.778 - MAURICIO PLOSZAI TAPECARIA AUTOMOTIVA
Dados Cadastrais da Matriz
CNPJ: 49.084.778/0001-15
"""

PERSON_SAMPLE_TEXT = """
MINISTÉRIO DA FAZENDA
CPF do certificado: 008.277.691-13
CPF: 000.523.221-06 - RENNAN KENNEDY DE CARVALHO ROJAS
Dados Cadastrais
"""


class ExtractionTests(unittest.TestCase):
    def test_extracts_company_from_report_header(self) -> None:
        self.assertEqual(
            extract_company_name_from_text(SAMPLE_TEXT),
            "MAURICIO PLOSZAI TAPECARIA AUTOMOTIVA",
        )

    def test_returns_none_when_header_is_missing(self) -> None:
        self.assertIsNone(extract_company_name_from_text("CNPJ: 12.345.678/0001-90"))

    def test_extracts_person_from_cpf_report_header(self) -> None:
        self.assertEqual(
            extract_company_name_from_text(PERSON_SAMPLE_TEXT),
            "RENNAN KENNEDY DE CARVALHO ROJAS",
        )

    def test_sanitizes_windows_filename(self) -> None:
        self.assertEqual(
            sanitize_filename('EMPRESA: TESTE / MATRIZ?'),
            "EMPRESA- TESTE - MATRIZ-.pdf",
        )

    def test_protects_reserved_windows_filename(self) -> None:
        self.assertEqual(sanitize_filename("CON"), "_CON.pdf")


class RenameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.folder = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @patch("renomeador_pdfs.extract_company_name_from_pdf")
    def test_analyzes_and_renames_a_pdf(self, extractor) -> None:
        source = self.folder / "relatorio-123.pdf"
        source.write_bytes(b"fake pdf")
        extractor.return_value = "EMPRESA EXEMPLO LTDA"

        plans = analyze_folder(self.folder)

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].target.name, "EMPRESA EXEMPLO LTDA.pdf")
        self.assertEqual(plans[0].status, "ready")

        results = apply_renames(plans)
        self.assertEqual(results[0].status, "renamed")
        self.assertTrue((self.folder / "EMPRESA EXEMPLO LTDA.pdf").exists())
        self.assertFalse(source.exists())

    @patch("renomeador_pdfs.extract_company_name_from_pdf")
    def test_adds_number_instead_of_overwriting(self, extractor) -> None:
        (self.folder / "relatorio.pdf").write_bytes(b"new")
        (self.folder / "EMPRESA.pdf").write_bytes(b"existing")
        extractor.return_value = "EMPRESA"

        plans = analyze_folder(self.folder)
        source_plan = next(plan for plan in plans if plan.source.name == "relatorio.pdf")

        self.assertEqual(source_plan.target.name, "EMPRESA (2).pdf")


if __name__ == "__main__":
    unittest.main()
