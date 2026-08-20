import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from parcelamentos import (
    InstallmentIdentification,
    analyze_installment_source,
    parse_installment_text,
    write_installment_zip,
)


DARF_TEXT = """
Documento de Arrecadação de Receitas Federais
DARF
02 PERÍODO DE APURAÇÃO 31/08/2026
03 NÚMERO DO CPF OU CNPJ 45.925.869/0001-85
01 NOME / RAZÃO SOCIAL
   MAORI BLUE LTDA                          06 DATA DE VENCIMENTO 31/08/2026
Observações:
02110001200923013302435
25
"""

DAS_TEXT = """
Documento de Arrecadação do Simples Nacional
CNPJ Razão Social
29.705.491/0001-58 TOTAL SOLUCOES INDUSTRIAIS LTDA
Período de Apuração Data de Vencimento
agosto/2026 31/08/2026
DAS de PARCSN (Versão: 2.0.0)
Número do Parcelamento: 3
Parcela: 11/60
"""


class InstallmentParsingTests(unittest.TestCase):
    def test_parses_darf(self) -> None:
        result = parse_installment_text(
            DARF_TEXT,
            "45925869000185_MAORI_BLUE_LTDA_0001_SIEFPAR_"
            "02110001200923013302435_025_20260831.pdf",
        )
        self.assertEqual(result.document_type, "DARF")
        self.assertEqual(result.cnpj, "45925869000185")
        self.assertEqual(result.company, "MAORI BLUE LTDA")
        self.assertEqual(result.installment, 25)
        self.assertIsNone(result.installment_total)
        self.assertEqual(result.due_date, "31/08/2026")

    def test_parses_das(self) -> None:
        result = parse_installment_text(
            DAS_TEXT,
            "29705491000158_PARCSN_SIMPLIFICADO_202608_202608.pdf",
        )
        self.assertEqual(result.document_type, "DAS")
        self.assertEqual(result.cnpj, "29705491000158")
        self.assertEqual(result.company, "TOTAL SOLUCOES INDUSTRIAIS LTDA")
        self.assertEqual(result.installment, 11)
        self.assertEqual(result.installment_total, 60)
        self.assertEqual(result.due_date, "31/08/2026")


class InstallmentSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.folder = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @patch("parcelamentos.extract_installment_from_pdf_source")
    def test_analyzes_zip_and_writes_renamed_zip(self, extractor) -> None:
        source = self.folder / "parcelamentos.zip"
        output = self.folder / "parcelamentos-renomeados.zip"
        with ZipFile(source, "w") as archive:
            archive.writestr("primeiro.pdf", b"primeiro")
            archive.writestr("segundo.pdf", b"segundo")
        extractor.side_effect = [
            InstallmentIdentification(
                "DARF", "45925869000185", "MAORI BLUE LTDA", 25, None, "31/08/2026"
            ),
            InstallmentIdentification(
                "DAS",
                "29705491000158",
                "TOTAL SOLUCOES INDUSTRIAIS LTDA",
                11,
                60,
                "31/08/2026",
            ),
        ]

        analysis = analyze_installment_source(source)

        self.assertEqual(
            analysis.plans[0].target_name,
            "MAORI BLUE LTDA - DARF - PARCELA 25 - 31-08-2026.pdf",
        )
        self.assertEqual(
            analysis.plans[1].target_name,
            "TOTAL SOLUCOES INDUSTRIAIS LTDA - DAS - PARCELA 11 DE 60 - "
            "31-08-2026.pdf",
        )

        write_installment_zip(analysis, output)
        with ZipFile(output) as renamed:
            self.assertEqual(
                renamed.namelist(),
                [
                    "MAORI BLUE LTDA - DARF - PARCELA 25 - 31-08-2026.pdf",
                    "TOTAL SOLUCOES INDUSTRIAIS LTDA - DAS - PARCELA 11 DE 60 - "
                    "31-08-2026.pdf",
                ],
            )


if __name__ == "__main__":
    unittest.main()
