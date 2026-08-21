from __future__ import annotations

import re
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable
from zipfile import ZipFile

from pypdf import PdfReader

from certidoes_estaduais import (
    AnalysisResult as CertificateAnalysis,
    CertificatePlan,
    format_cnpj,
    is_valid_cnpj,
    only_digits,
    write_renamed_zip as write_certificate_zip,
)
from renomeador_pdfs import MAX_FILENAME_LENGTH, sanitize_filename


ProgressCallback = Callable[[int, int, str], None]
CNPJ_PATTERN = re.compile(
    r"(?<!\d)(\d{2}\s*\.?\s*\d{3}\s*\.?\s*\d{3}"
    r"\s*/?\s*\d{4}\s*-?\s*\d{2})(?!\d)"
)
DATE_PATTERN = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")


@dataclass(frozen=True)
class InstallmentIdentification:
    document_type: str
    cnpj: str
    company: str
    installment: int | None
    installment_total: int | None
    due_date: str | None


@dataclass(frozen=True)
class InstallmentPlan:
    source_name: str
    source_path: Path | None
    zip_entry: str | None
    document_type: str | None
    cnpj: str | None
    company: str | None
    installment: int | None
    installment_total: int | None
    due_date: str | None
    target_name: str | None
    status: str
    message: str = ""


@dataclass(frozen=True)
class InstallmentAnalysis:
    source: Path
    source_kind: str
    plans: list[InstallmentPlan]


def _find_cnpj(text: str, source_name: str) -> str:
    for match in CNPJ_PATTERN.finditer(text):
        candidate = only_digits(match.group(1))
        if is_valid_cnpj(candidate):
            return candidate
    filename_match = re.search(r"(?<!\d)(\d{14})(?!\d)", source_name)
    if filename_match and is_valid_cnpj(filename_match.group(1)):
        return filename_match.group(1)
    raise ValueError("nenhum CNPJ válido foi encontrado")


def _company_from_cnpj_line(text: str) -> str | None:
    for line in text.splitlines():
        match = CNPJ_PATTERN.search(line)
        if not match:
            continue
        suffix = re.sub(r"\s+", " ", line[match.end() :]).strip(" :-")
        if suffix and re.search(r"[A-Za-zÀ-ÿ]", suffix):
            return suffix
    return None


def _company_from_darf_label(text: str) -> str | None:
    match = re.search(
        r"(?im)^\s*(?:01\s+)?NOME\s*/\s*RAZÃO SOCIAL\s*$\s*\n\s*(.+)$",
        text,
    )
    if not match:
        return None
    company = re.split(
        r"\s{2,}(?:06\b|DATA DE VENCIMENTO)",
        match.group(1),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    company = re.sub(r"\s+", " ", company).strip()
    return company or None


def _company_from_filename(source_name: str) -> str | None:
    filename = PurePosixPath(source_name.replace("\\", "/")).name
    match = re.match(
        r"^\d{14}_(?P<company>.+?)_\d{4}_SIEFPAR_",
        filename,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    company = re.sub(r"_+", " ", match.group("company"))
    return re.sub(r"\s+", " ", company).strip() or None


def _find_due_date(text: str, document_type: str, source_name: str) -> str | None:
    if document_type == "DARF":
        match = re.search(
            r"DATA DE VENCIMENTO[^\n]*(\d{2}/\d{2}/\d{4})",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1)
    else:
        match = re.search(
            r"Data de Vencimento[\s\S]{0,180}?(\d{2}/\d{2}/\d{4})",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1)

    filename = PurePosixPath(source_name.replace("\\", "/")).name
    compact = re.search(r"_(20\d{6})(?:\.pdf)?$", filename, flags=re.IGNORECASE)
    if compact:
        value = compact.group(1)
        return f"{value[6:8]}/{value[4:6]}/{value[:4]}"
    dates = DATE_PATTERN.findall(text)
    return dates[0] if dates else None


def _find_installment(
    text: str,
    document_type: str,
    source_name: str,
) -> tuple[int | None, int | None]:
    if document_type == "DAS":
        match = re.search(
            r"Parcela\s*:\s*(\d+)\s*/\s*(\d+)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return int(match.group(1)), int(match.group(2))
    else:
        match = re.search(
            r"Observações:[\s\S]{0,400}?\n\s*(\d{15,})[^\n]*\n\s*(\d{1,3})\b",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return int(match.group(2)), None
        filename = PurePosixPath(source_name.replace("\\", "/")).name
        filename_match = re.search(
            r"_SIEFPAR_[^_]+_(\d{1,3})_\d{8}(?:\.pdf)?$",
            filename,
            flags=re.IGNORECASE,
        )
        if filename_match:
            return int(filename_match.group(1)), None
    return None, None


def parse_installment_text(text: str, source_name: str) -> InstallmentIdentification:
    upper = text.upper()
    if "DOCUMENTO DE ARRECADAÇÃO DO SIMPLES NACIONAL" in upper or "DAS DE PARCSN" in upper:
        document_type = "DAS"
    elif "DOCUMENTO DE ARRECADAÇÃO DE RECEITAS FEDERAIS" in upper and "DARF" in upper:
        document_type = "DARF"
    else:
        raise ValueError("o documento não foi reconhecido como DARF ou DAS")

    cnpj = _find_cnpj(text, source_name)
    company = _company_from_cnpj_line(text)
    if not company and document_type == "DARF":
        company = _company_from_darf_label(text)
    if not company:
        company = _company_from_filename(source_name)
    if not company:
        raise ValueError("a razão social não foi encontrada")

    installment, installment_total = _find_installment(
        text,
        document_type,
        source_name,
    )
    due_date = _find_due_date(text, document_type, source_name)
    return InstallmentIdentification(
        document_type=document_type,
        cnpj=cnpj,
        company=company,
        installment=installment,
        installment_total=installment_total,
        due_date=due_date,
    )


def extract_installment_from_pdf_source(
    pdf_source: bytes | Path,
    source_name: str | None = None,
) -> InstallmentIdentification:
    source = BytesIO(pdf_source) if isinstance(pdf_source, bytes) else str(pdf_source)
    try:
        reader = PdfReader(source)
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise ValueError("o PDF está protegido por senha")
        if not reader.pages:
            raise ValueError("o PDF não possui páginas")
        page = reader.pages[0]
        try:
            text = page.extract_text(extraction_mode="layout") or ""
        except TypeError:
            text = page.extract_text() or ""
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"não foi possível ler o PDF: {exc}") from exc
    return parse_installment_text(text, source_name or str(pdf_source))


def _build_target_name(identification: InstallmentIdentification) -> str:
    parts = [identification.company, identification.document_type]
    if identification.installment is not None:
        if identification.installment_total is not None:
            parts.append(
                f"PARCELA {identification.installment} DE "
                f"{identification.installment_total}"
            )
        else:
            parts.append(f"PARCELA {identification.installment}")
    if identification.due_date:
        parts.append(identification.due_date.replace("/", "-"))
    return sanitize_filename(" - ".join(parts))


def _allocate_filename(filename: str, reserved: set[str]) -> str:
    stem = Path(filename).stem
    suffix = Path(filename).suffix or ".pdf"
    number = 1
    while True:
        if number == 1:
            candidate = f"{stem}{suffix}"
        else:
            extra = f" ({number})"
            allowed = MAX_FILENAME_LENGTH - len(suffix) - len(extra)
            candidate = f"{stem[:allowed].rstrip(' .')}{extra}{suffix}"
        key = candidate.casefold()
        if key not in reserved:
            reserved.add(key)
            return candidate
        number += 1


def _initial_plan(
    source_name: str,
    source_path: Path | None,
    zip_entry: str | None,
    pdf_source: bytes | Path,
) -> InstallmentPlan:
    try:
        identification = extract_installment_from_pdf_source(
            pdf_source,
            source_name=source_name,
        )
        return InstallmentPlan(
            source_name=source_name,
            source_path=source_path,
            zip_entry=zip_entry,
            document_type=identification.document_type,
            cnpj=identification.cnpj,
            company=identification.company,
            installment=identification.installment,
            installment_total=identification.installment_total,
            due_date=identification.due_date,
            target_name=_build_target_name(identification),
            status="identified",
        )
    except Exception as exc:
        return InstallmentPlan(
            source_name=source_name,
            source_path=source_path,
            zip_entry=zip_entry,
            document_type=None,
            cnpj=None,
            company=None,
            installment=None,
            installment_total=None,
            due_date=None,
            target_name=None,
            status="error",
            message=str(exc),
        )


def _complete_plans(
    plans: list[InstallmentPlan],
    existing_names: Iterable[str] = (),
) -> list[InstallmentPlan]:
    reserved = {name.casefold() for name in existing_names}
    completed: list[InstallmentPlan] = []
    for plan in plans:
        if plan.status == "error" or not plan.target_name:
            completed.append(plan)
            continue
        current_name = PurePosixPath(plan.source_name.replace("\\", "/")).name
        if plan.source_path and current_name.casefold() == plan.target_name.casefold():
            completed.append(
                replace(
                    plan,
                    target_name=current_name,
                    status="already_named",
                    message="já está com o nome correto",
                )
            )
            continue
        target_name = _allocate_filename(plan.target_name, reserved)
        message = plan.message
        if target_name != plan.target_name:
            message = "número adicionado para preservar arquivos repetidos"
        completed.append(
            replace(
                plan,
                target_name=target_name,
                status="ready",
                message=message,
            )
        )
    return completed


def _progress(
    callback: ProgressCallback | None,
    current: int,
    total: int,
    message: str,
) -> None:
    if callback and (current == total or current == 1 or current % 25 == 0):
        callback(current, total, message)


def analyze_installment_source(
    source: Path,
    progress: ProgressCallback | None = None,
) -> InstallmentAnalysis:
    source = source.expanduser().resolve()
    plans: list[InstallmentPlan] = []
    if source.is_file() and source.suffix.lower() == ".zip":
        source_kind = "zip"
        with ZipFile(source) as archive:
            entries = [
                info
                for info in archive.infolist()
                if not info.is_dir() and info.filename.lower().endswith(".pdf")
            ]
            total = len(entries)
            for index, info in enumerate(entries, 1):
                _progress(progress, index, total, f"Lendo PDFs: {index}/{total}")
                plans.append(
                    _initial_plan(
                        info.filename,
                        None,
                        info.filename,
                        archive.read(info),
                    )
                )
        completed = _complete_plans(plans)
    elif source.is_dir():
        source_kind = "folder"
        pdfs = sorted(
            (
                path
                for path in source.iterdir()
                if path.is_file() and path.suffix.lower() == ".pdf"
            ),
            key=lambda path: path.name.casefold(),
        )
        total = len(pdfs)
        for index, pdf_path in enumerate(pdfs, 1):
            _progress(progress, index, total, f"Lendo PDFs: {index}/{total}")
            plans.append(
                _initial_plan(
                    pdf_path.name,
                    pdf_path,
                    None,
                    pdf_path,
                )
            )
        completed = _complete_plans(
            plans,
            (path.name for path in source.iterdir() if path.is_file()),
        )
    else:
        raise ValueError("selecione uma pasta ou um arquivo ZIP válido")
    return InstallmentAnalysis(source=source, source_kind=source_kind, plans=completed)


def summarize_installments(plans: Iterable[InstallmentPlan]) -> dict[str, int]:
    counts = {"ready": 0, "renamed": 0, "already_named": 0, "error": 0}
    for plan in plans:
        counts[plan.status] = counts.get(plan.status, 0) + 1
    return counts


def apply_installment_folder_renames(
    plans: Iterable[InstallmentPlan],
    progress: ProgressCallback | None = None,
) -> list[InstallmentPlan]:
    plan_list = list(plans)
    results: list[InstallmentPlan] = []
    for index, plan in enumerate(plan_list, 1):
        _progress(progress, index, len(plan_list), f"Renomeando: {index}/{len(plan_list)}")
        if plan.status != "ready" or not plan.source_path or not plan.target_name:
            results.append(plan)
            continue
        target = plan.source_path.with_name(plan.target_name)
        try:
            if not plan.source_path.exists():
                raise FileNotFoundError("o arquivo original não existe mais")
            if target.exists():
                raise FileExistsError(
                    "o nome de destino passou a existir; analise novamente"
                )
            plan.source_path.rename(target)
            results.append(
                replace(
                    plan,
                    source_path=target,
                    source_name=target.name,
                    status="renamed",
                    message="renomeado com sucesso",
                )
            )
        except Exception as exc:
            results.append(replace(plan, status="error", message=str(exc)))
    return results


def write_installment_zip(
    analysis: InstallmentAnalysis,
    output_path: Path,
    progress: ProgressCallback | None = None,
) -> Path:
    converted = [
        CertificatePlan(
            source_name=plan.source_name,
            source_path=None,
            zip_entry=plan.zip_entry,
            cnpj=plan.cnpj,
            cnpj_origin="PDF",
            company=plan.company,
            target_name=plan.target_name,
            status=plan.status,
            message=plan.message,
        )
        for plan in analysis.plans
    ]
    converted_analysis = CertificateAnalysis(
        source=analysis.source,
        source_kind="zip",
        plans=converted,
    )
    return write_certificate_zip(converted_analysis, output_path, progress)


def installment_label(plan: InstallmentPlan) -> str:
    if plan.installment is None:
        return "-"
    if plan.installment_total is not None:
        return f"{plan.installment}/{plan.installment_total}"
    return str(plan.installment)


def create_installment_panel_class(base_panel: type) -> type:
    class InstallmentPanel(base_panel):
        def __init__(self, parent) -> None:
            super().__init__(
                parent,
                title="Renomear parcelamentos DARF e DAS",
                description=(
                    "O sistema diferencia DARF e DAS automaticamente e inclui parcela e "
                    "vencimento no novo nome. Não precisa de internet."
                ),
                category="Reconhecimento automático",
                columns=(
                    "current",
                    "type",
                    "cnpj",
                    "company",
                    "installment",
                    "due",
                    "new",
                    "status",
                ),
                headings={
                    "current": "Arquivo atual",
                    "type": "Tipo",
                    "cnpj": "CNPJ",
                    "company": "Razão social",
                    "installment": "Parcela",
                    "due": "Vencimento",
                    "new": "Novo nome",
                    "status": "Situação",
                },
                widths={
                    "current": 260,
                    "type": 70,
                    "cnpj": 145,
                    "company": 260,
                    "installment": 80,
                    "due": 100,
                    "new": 370,
                    "status": 220,
                },
            )

        @property
        def result(self) -> InstallmentAnalysis:
            assert isinstance(self.analysis, InstallmentAnalysis)
            return self.analysis

        def perform_analysis(
            self,
            source: Path,
            progress: ProgressCallback,
        ) -> InstallmentAnalysis:
            return analyze_installment_source(source, progress)

        def perform_output(
            self,
            output_path: Path | None,
            progress: ProgressCallback,
        ) -> tuple[InstallmentAnalysis, Path | None]:
            if self.result.source_kind == "zip":
                if output_path is None:
                    raise ValueError("o arquivo de saída não foi informado")
                written = write_installment_zip(self.result, output_path, progress)
                return self.result, written
            plans = apply_installment_folder_renames(self.result.plans, progress)
            return replace(self.result, plans=plans), None

        def table_rows(self):
            labels = {
                "ready": "Pronto",
                "renamed": "Renomeado",
                "already_named": "Já está correto",
                "error": "Erro",
            }
            for plan in self.result.plans:
                status = labels.get(plan.status, plan.status)
                if plan.message:
                    status = f"{status}: {plan.message}"
                yield (
                    plan.source_name,
                    plan.document_type or "-",
                    format_cnpj(plan.cnpj or ""),
                    plan.company or "-",
                    installment_label(plan),
                    plan.due_date or "-",
                    plan.target_name or "-",
                    status,
                )

        def ready_count(self) -> int:
            return summarize_installments(self.result.plans)["ready"]

        def plan_count(self) -> int:
            return len(self.result.plans)

        def analysis_summary(self) -> str:
            counts = summarize_installments(self.result.plans)
            darf = sum(1 for plan in self.result.plans if plan.document_type == "DARF")
            das = sum(1 for plan in self.result.plans if plan.document_type == "DAS")
            return (
                f"{len(self.result.plans)} PDF(s): {darf} DARF, {das} DAS, "
                f"{counts['ready']} pronto(s), {counts['error']} erro(s)."
            )

        def output_summary(self) -> str:
            counts = summarize_installments(self.result.plans)
            return (
                f"Concluído: {counts['renamed']} renomeado(s), "
                f"{counts['already_named']} já correto(s), {counts['error']} erro(s)."
            )

    InstallmentPanel.__name__ = "InstallmentPanel"
    return InstallmentPanel
