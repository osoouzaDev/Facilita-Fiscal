import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from facilita_fiscal import (
    analyze_situation_source,
    apply_situation_folder_renames,
    summarize_situation,
    write_situation_zip,
)


class SituationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.folder = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @patch("facilita_fiscal.extract_company_from_pdf_source")
    def test_analyzes_and_renames_pdfs_in_folder(self, extractor) -> None:
        source = self.folder / "relatorio.pdf"
        source.write_bytes(b"pdf de teste")
        extractor.return_value = "EMPRESA EXEMPLO LTDA"

        analysis = analyze_situation_source(self.folder)
        self.assertEqual(analysis.source_kind, "folder")
        self.assertEqual(analysis.plans[0].target_name, "EMPRESA EXEMPLO LTDA.pdf")

        plans = apply_situation_folder_renames(analysis.plans)
        self.assertEqual(plans[0].status, "renamed")
        self.assertTrue((self.folder / "EMPRESA EXEMPLO LTDA.pdf").exists())

    @patch("facilita_fiscal.extract_company_from_pdf_source")
    def test_analyzes_zip_and_writes_new_zip(self, extractor) -> None:
        source = self.folder / "relatorios.zip"
        output = self.folder / "relatorios-renomeados.zip"
        with ZipFile(source, "w") as archive:
            archive.writestr("primeiro.pdf", b"primeiro")
            archive.writestr("segundo.pdf", b"segundo")
        extractor.return_value = "EMPRESA EXEMPLO LTDA"

        analysis = analyze_situation_source(source)

        self.assertEqual(analysis.source_kind, "zip")
        self.assertEqual(summarize_situation(analysis.plans)["ready"], 2)
        self.assertEqual(analysis.plans[0].target_name, "EMPRESA EXEMPLO LTDA.pdf")
        self.assertEqual(analysis.plans[1].target_name, "EMPRESA EXEMPLO LTDA (2).pdf")

        write_situation_zip(analysis, output)

        with ZipFile(source) as original:
            self.assertEqual(original.namelist(), ["primeiro.pdf", "segundo.pdf"])
        with ZipFile(output) as renamed:
            self.assertEqual(
                renamed.namelist(),
                ["EMPRESA EXEMPLO LTDA.pdf", "EMPRESA EXEMPLO LTDA (2).pdf"],
            )


if __name__ == "__main__":
    unittest.main()
