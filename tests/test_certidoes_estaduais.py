import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from certidoes_estaduais import (
    AnalysisResult,
    BrasilApiClient,
    CnpjCache,
    CertificatePlan,
    ResilientCnpjClient,
    _complete_plans,
    cnpj_from_filename,
    extract_cnpj,
    format_cnpj,
    is_valid_cnpj,
    lookup_companies,
    matrix_cnpj_from_root,
    write_renamed_zip,
)


class FakeClient(BrasilApiClient):
    def __init__(self, companies: dict[str, str]) -> None:
        self.companies = companies
        self.calls: list[str] = []

    def lookup(self, cnpj: str) -> str:
        self.calls.append(cnpj)
        return self.companies[cnpj]


class FailingClient(BrasilApiClient):
    def lookup(self, cnpj: str) -> str:
        raise ValueError("serviço principal indisponível")


class CnpjExtractionTests(unittest.TestCase):
    def test_validates_and_formats_cnpj(self) -> None:
        self.assertTrue(is_valid_cnpj("12.002.041/0001-04"))
        self.assertFalse(is_valid_cnpj("12.002.041/0001-00"))
        self.assertEqual(format_cnpj("12002041000104"), "12.002.041/0001-04")

    def test_builds_matrix_cnpj_from_root(self) -> None:
        self.assertEqual(matrix_cnpj_from_root("38.076.926"), "38076926000133")
        self.assertTrue(is_valid_cnpj(matrix_cnpj_from_root("38.076.926")))

    def test_extracts_cnpj_from_pdf_and_filename(self) -> None:
        identification = extract_cnpj(
            "Certidão fornecida para o CNPJ/MF: 12.002.041/0001-04",
            "12002041000104_123.pdf",
        )
        self.assertEqual(identification.cnpj, "12002041000104")
        self.assertEqual(identification.origin, "PDF e nome do arquivo")

    def test_uses_full_cnpj_from_filename_when_pdf_has_no_text(self) -> None:
        identification = cnpj_from_filename("33091761000155_.pdf")
        self.assertIsNotNone(identification)
        self.assertEqual(identification.cnpj, "33091761000155")

    def test_uses_matrix_for_rj_root_filename(self) -> None:
        identification = cnpj_from_filename(
            "CND_RJ_38076926_2026183282897_2026 13:150802.pdf"
        )
        self.assertIsNotNone(identification)
        self.assertEqual(identification.cnpj, "38076926000133")


class LookupAndPlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.cache_path = Path(self.temporary.name) / "cache.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_uses_cache_and_queries_each_cnpj_once(self) -> None:
        cache = CnpjCache(self.cache_path)
        cache.set("12002041000104", "EMPRESA EM CACHE")
        cache.save()
        client = FakeClient({"38076926000133": "EMPRESA CONSULTADA"})

        companies, errors = lookup_companies(
            ["12002041000104", "38076926000133", "38076926000133"],
            cache=cache,
            client=client,
        )

        self.assertEqual(errors, {})
        self.assertEqual(companies["12002041000104"], "EMPRESA EM CACHE")
        self.assertEqual(companies["38076926000133"], "EMPRESA CONSULTADA")
        self.assertEqual(client.calls, ["38076926000133"])

    def test_uses_contingency_when_primary_service_fails(self) -> None:
        fallback = FakeClient({"12002041000104": "EMPRESA DA CONTINGENCIA"})
        client = ResilientCnpjClient(primary=FailingClient(), fallback=fallback)

        company = client.lookup("12002041000104")

        self.assertEqual(company, "EMPRESA DA CONTINGENCIA")
        self.assertEqual(fallback.calls, ["12002041000104"])

    def test_adds_number_for_repeated_certificates(self) -> None:
        plans = [
            CertificatePlan(
                source_name=f"certidao-{number}.pdf",
                source_path=None,
                zip_entry=f"certidao-{number}.pdf",
                cnpj="12002041000104",
                cnpj_origin="PDF",
                company=None,
                target_name=None,
                status="identified",
            )
            for number in range(2)
        ]

        completed = _complete_plans(
            plans,
            companies={"12002041000104": "EMPRESA EXEMPLO LTDA"},
            lookup_errors={},
        )

        self.assertEqual(completed[0].target_name, "EMPRESA EXEMPLO LTDA.pdf")
        self.assertEqual(completed[1].target_name, "EMPRESA EXEMPLO LTDA (2).pdf")

    def test_writes_new_zip_and_preserves_original(self) -> None:
        source = Path(self.temporary.name) / "originais.zip"
        output = Path(self.temporary.name) / "renomeados.zip"
        with ZipFile(source, "w") as archive:
            archive.writestr("primeiro.pdf", b"primeiro")
            archive.writestr("segundo.pdf", b"segundo")

        plans = [
            CertificatePlan(
                source_name="primeiro.pdf",
                source_path=None,
                zip_entry="primeiro.pdf",
                cnpj="12002041000104",
                cnpj_origin="nome do arquivo",
                company="EMPRESA EXEMPLO LTDA",
                target_name="EMPRESA EXEMPLO LTDA.pdf",
                status="ready",
            ),
            CertificatePlan(
                source_name="segundo.pdf",
                source_path=None,
                zip_entry="segundo.pdf",
                cnpj="12002041000104",
                cnpj_origin="nome do arquivo",
                company="EMPRESA EXEMPLO LTDA",
                target_name="EMPRESA EXEMPLO LTDA (2).pdf",
                status="ready",
            ),
        ]
        analysis = AnalysisResult(source=source, source_kind="zip", plans=plans)

        write_renamed_zip(analysis, output)

        with ZipFile(source) as original:
            self.assertEqual(original.namelist(), ["primeiro.pdf", "segundo.pdf"])
        with ZipFile(output) as renamed:
            self.assertEqual(
                renamed.namelist(),
                ["EMPRESA EXEMPLO LTDA.pdf", "EMPRESA EXEMPLO LTDA (2).pdf"],
            )
            self.assertEqual(renamed.read("EMPRESA EXEMPLO LTDA.pdf"), b"primeiro")


if __name__ == "__main__":
    unittest.main()
