from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Protocol
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from renomeador_pdfs import MAX_FILENAME_LENGTH, sanitize_filename


APP_TITLE = "Renomeador de Certidões Estaduais"
BRASIL_API_URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
CNPJA_PUBLIC_API_URL = "https://open.cnpja.com/office/{cnpj}"
ProgressCallback = Callable[[int, int, str], None]

CNPJ_PATTERN = re.compile(
    r"(?<!\d)(\d{2}\s*\.?\s*\d{3}\s*\.?\s*\d{3}"
    r"\s*/?\s*\d{4}\s*-?\s*\d{2})(?!\d)"
)
ROOT_PATTERN = re.compile(
    r"(?:CPF\s*/\s*RAIZ\s+DO\s+CNPJ|RAIZ\s+DO\s+CNPJ|CNPJ)"
    r"[^0-9]{0,15}(\d{2}\s*\.?\s*\d{3}\s*\.?\s*\d{3})(?!\d)",
    flags=re.IGNORECASE,
)
FILENAME_PREFIX_PATTERN = re.compile(
    r"^(?:CND_[A-Z]{2}_)?(?P<identifier>\d{14}|\d{8})(?:_|\.|$)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class CnpjIdentification:
    cnpj: str
    origin: str


@dataclass(frozen=True)
class CertificatePlan:
    source_name: str
    source_path: Path | None
    zip_entry: str | None
    cnpj: str | None
    cnpj_origin: str | None
    company: str | None
    target_name: str | None
    status: str
    message: str = ""


@dataclass(frozen=True)
class AnalysisResult:
    source: Path
    source_kind: str
    plans: list[CertificatePlan]


def only_digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _check_digit(base: str, weights: list[int]) -> str:
    total = sum(int(number) * weight for number, weight in zip(base, weights))
    remainder = total % 11
    return "0" if remainder < 2 else str(11 - remainder)


def is_valid_cnpj(cnpj: str) -> bool:
    cnpj = only_digits(cnpj)
    if len(cnpj) != 14 or len(set(cnpj)) == 1:
        return False

    first = _check_digit(cnpj[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    second = _check_digit(
        cnpj[:12] + first,
        [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2],
    )
    return cnpj[-2:] == first + second


def matrix_cnpj_from_root(root: str) -> str:
    root = only_digits(root)
    if len(root) != 8:
        raise ValueError("a raiz do CNPJ deve possuir 8 dígitos")

    base = root + "0001"
    first = _check_digit(base, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    second = _check_digit(
        base + first,
        [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2],
    )
    return base + first + second


def format_cnpj(cnpj: str) -> str:
    cnpj = only_digits(cnpj)
    if len(cnpj) != 14:
        return cnpj
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"


def cnpj_from_filename(source_name: str) -> CnpjIdentification | None:
    filename = PurePosixPath(source_name.replace("\\", "/")).name
    match = FILENAME_PREFIX_PATTERN.match(filename)
    if match:
        identifier = match.group("identifier")
        if len(identifier) == 14 and is_valid_cnpj(identifier):
            return CnpjIdentification(identifier, "nome do arquivo")
        if len(identifier) == 8:
            return CnpjIdentification(
                matrix_cnpj_from_root(identifier),
                "raiz no nome do arquivo",
            )

    for candidate_match in CNPJ_PATTERN.finditer(filename):
        candidate = only_digits(candidate_match.group(1))
        if is_valid_cnpj(candidate):
            return CnpjIdentification(candidate, "nome do arquivo")
    return None


def extract_cnpj(text: str, source_name: str) -> CnpjIdentification:
    filename_identification = cnpj_from_filename(source_name)
    text_candidates: list[str] = []

    for match in CNPJ_PATTERN.finditer(text):
        candidate = only_digits(match.group(1))
        if is_valid_cnpj(candidate) and candidate not in text_candidates:
            text_candidates.append(candidate)

    if filename_identification and filename_identification.cnpj in text_candidates:
        return CnpjIdentification(
            filename_identification.cnpj,
            "PDF e nome do arquivo",
        )

    if filename_identification and any(
        candidate[:8] == filename_identification.cnpj[:8]
        for candidate in text_candidates
    ):
        return CnpjIdentification(
            filename_identification.cnpj,
            "PDF e raiz no nome do arquivo",
        )

    if len(text_candidates) == 1:
        return CnpjIdentification(text_candidates[0], "PDF")

    if filename_identification:
        return filename_identification

    if len(text_candidates) > 1:
        raise ValueError("mais de um CNPJ válido foi encontrado; confira manualmente")

    roots = []
    for match in ROOT_PATTERN.finditer(text):
        root = only_digits(match.group(1))
        if len(root) == 8 and root not in roots:
            roots.append(root)
    if len(roots) == 1:
        return CnpjIdentification(matrix_cnpj_from_root(roots[0]), "raiz no PDF")

    raise ValueError("nenhum CNPJ válido foi encontrado")


def extract_pdf_text(pdf_data: bytes | Path, max_pages: int = 3) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("a biblioteca pypdf não está instalada") from exc

    source = BytesIO(pdf_data) if isinstance(pdf_data, bytes) else str(pdf_data)
    reader = PdfReader(source)
    if reader.is_encrypted and reader.decrypt("") == 0:
        raise ValueError("o PDF está protegido por senha")
    return "\n".join((page.extract_text() or "") for page in reader.pages[:max_pages])


def default_cache_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "FacilitaFiscal" / "cnpj_cache.json"
    return Path.home() / ".facilita_fiscal" / "cnpj_cache.json"


class CnpjCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_cache_path()
        self.entries: dict[str, dict[str, str]] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            entries = data.get("entries", {})
            if isinstance(entries, dict):
                self.entries = entries
        except (OSError, ValueError, TypeError):
            self.entries = {}

    def get(self, cnpj: str) -> str | None:
        entry = self.entries.get(cnpj)
        if not isinstance(entry, dict):
            return None
        company = entry.get("razao_social")
        return company.strip() if isinstance(company, str) and company.strip() else None

    def set(
        self,
        cnpj: str,
        company: str,
        source: str = "Consulta pública de CNPJ",
    ) -> None:
        self.entries[cnpj] = {
            "razao_social": company.strip(),
            "fonte": source,
            "consultado_em": datetime.now(timezone.utc).isoformat(),
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        payload = {"version": 1, "entries": self.entries}
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()


class CnpjLookupClient(Protocol):
    def lookup(self, cnpj: str) -> str:
        ...


class BrasilApiClient:
    def __init__(self, timeout: int = 25, attempts: int = 4) -> None:
        self.timeout = timeout
        self.attempts = attempts

    def lookup(self, cnpj: str) -> str:
        url = BRASIL_API_URL.format(cnpj=cnpj)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "FacilitaFiscal-Certidoes/1.0",
            },
        )

        for attempt in range(self.attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                company = data.get("razao_social")
                if not isinstance(company, str) or not company.strip():
                    raise ValueError("a consulta não retornou a razão social")
                return company.strip()
            except urllib.error.HTTPError as exc:
                if exc.code in (400, 404):
                    raise ValueError(f"CNPJ não encontrado na consulta ({exc.code})") from exc
                if exc.code != 429 and exc.code < 500:
                    raise ValueError(f"consulta recusada pela API ({exc.code})") from exc
                if attempt == self.attempts - 1:
                    raise ValueError(f"serviço de consulta indisponível ({exc.code})") from exc
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                time.sleep(min(delay, 10))
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                if attempt == self.attempts - 1:
                    raise ValueError(f"falha de conexão com a consulta: {exc}") from exc
                time.sleep(min(2**attempt, 10))

        raise ValueError("não foi possível consultar o CNPJ")


class CnpjaPublicClient:
    """Cliente de contingência com limite compartilhado de 5 consultas/minuto."""

    def __init__(self, timeout: int = 25, min_interval: float = 12.5) -> None:
        self.timeout = timeout
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last_request = 0.0

    def lookup(self, cnpj: str) -> str:
        url = CNPJA_PUBLIC_API_URL.format(cnpj=cnpj)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "FacilitaFiscal-Certidoes/1.0",
            },
        )

        with self._lock:
            elapsed = time.monotonic() - self._last_request
            delay = self.min_interval - elapsed
            if delay > 0:
                time.sleep(delay)

            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                company_data = data.get("company")
                company = (
                    company_data.get("name")
                    if isinstance(company_data, dict)
                    else None
                )
                if not isinstance(company, str) or not company.strip():
                    raise ValueError("a contingência não retornou a razão social")
                return company.strip()
            except urllib.error.HTTPError as exc:
                if exc.code in (400, 404):
                    raise ValueError(
                        f"CNPJ não encontrado na contingência ({exc.code})"
                    ) from exc
                raise ValueError(
                    f"serviço de contingência indisponível ({exc.code})"
                ) from exc
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"falha de conexão com a contingência: {exc}") from exc
            finally:
                self._last_request = time.monotonic()


class ResilientCnpjClient:
    def __init__(
        self,
        primary: CnpjLookupClient | None = None,
        fallback: CnpjLookupClient | None = None,
    ) -> None:
        self.primary = primary or BrasilApiClient()
        self.fallback = fallback or CnpjaPublicClient()

    def lookup(self, cnpj: str) -> str:
        try:
            return self.primary.lookup(cnpj)
        except Exception as primary_error:
            try:
                return self.fallback.lookup(cnpj)
            except Exception as fallback_error:
                raise ValueError(
                    f"consulta principal: {primary_error}; "
                    f"contingência: {fallback_error}"
                ) from fallback_error


def lookup_companies(
    cnpjs: Iterable[str],
    cache: CnpjCache,
    client: CnpjLookupClient | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    client = client or ResilientCnpjClient()
    unique = sorted(set(cnpjs))
    companies: dict[str, str] = {}
    errors: dict[str, str] = {}
    pending: list[str] = []

    for cnpj in unique:
        cached = cache.get(cnpj)
        if cached:
            companies[cnpj] = cached
        else:
            pending.append(cnpj)

    total = len(unique)
    completed = len(companies)
    if progress:
        progress(completed, total, f"{completed} CNPJ(s) recuperado(s) do cache")

    if pending:
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(client.lookup, cnpj): cnpj for cnpj in pending}
            unsaved = 0
            for future in as_completed(futures):
                cnpj = futures[future]
                try:
                    company = future.result()
                    companies[cnpj] = company
                    cache.set(cnpj, company)
                    unsaved += 1
                    if unsaved >= 10:
                        cache.save()
                        unsaved = 0
                except Exception as exc:
                    errors[cnpj] = str(exc)
                completed += 1
                if progress:
                    progress(completed, total, f"Consultando CNPJs: {completed}/{total}")
            if unsaved:
                cache.save()

    return companies, errors


def _progress(
    callback: ProgressCallback | None,
    current: int,
    total: int,
    message: str,
) -> None:
    if callback and (current == total or current == 1 or current % 25 == 0):
        callback(current, total, message)


def _identified_plan(
    source_name: str,
    source_path: Path | None,
    zip_entry: str | None,
    pdf_source: bytes | Path,
) -> CertificatePlan:
    try:
        text = extract_pdf_text(pdf_source)
        identification = extract_cnpj(text, source_name)
        return CertificatePlan(
            source_name=source_name,
            source_path=source_path,
            zip_entry=zip_entry,
            cnpj=identification.cnpj,
            cnpj_origin=identification.origin,
            company=None,
            target_name=None,
            status="identified",
        )
    except Exception as pdf_error:
        filename_identification = cnpj_from_filename(source_name)
        if filename_identification:
            return CertificatePlan(
                source_name=source_name,
                source_path=source_path,
                zip_entry=zip_entry,
                cnpj=filename_identification.cnpj,
                cnpj_origin=filename_identification.origin,
                company=None,
                target_name=None,
                status="identified",
                message=f"PDF sem texto útil; {filename_identification.origin}",
            )
        return CertificatePlan(
            source_name=source_name,
            source_path=source_path,
            zip_entry=zip_entry,
            cnpj=None,
            cnpj_origin=None,
            company=None,
            target_name=None,
            status="error",
            message=str(pdf_error),
        )


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


def _complete_plans(
    plans: list[CertificatePlan],
    companies: dict[str, str],
    lookup_errors: dict[str, str],
    existing_names: Iterable[str] = (),
) -> list[CertificatePlan]:
    reserved = {name.casefold() for name in existing_names}
    completed: list[CertificatePlan] = []

    for plan in plans:
        if plan.status == "error" or not plan.cnpj:
            completed.append(plan)
            continue
        company = companies.get(plan.cnpj)
        if not company:
            completed.append(
                replace(
                    plan,
                    status="error",
                    message=lookup_errors.get(plan.cnpj, "razão social não encontrada"),
                )
            )
            continue
        filename = sanitize_filename(company)
        target_name = _allocate_filename(filename, reserved)
        message = plan.message
        if target_name != filename:
            message = "número adicionado para preservar certidões repetidas"
        completed.append(
            replace(
                plan,
                company=company,
                target_name=target_name,
                status="ready",
                message=message,
            )
        )
    return completed


def analyze_source(
    source: Path,
    cache_path: Path | None = None,
    client: CnpjLookupClient | None = None,
    progress: ProgressCallback | None = None,
) -> AnalysisResult:
    source = source.expanduser().resolve()
    plans: list[CertificatePlan] = []

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
                    _identified_plan(
                        source_name=info.filename,
                        source_path=None,
                        zip_entry=info.filename,
                        pdf_source=archive.read(info),
                    )
                )
    elif source.is_dir():
        source_kind = "folder"
        pdfs = sorted(
            (path for path in source.iterdir() if path.is_file() and path.suffix.lower() == ".pdf"),
            key=lambda path: path.name.casefold(),
        )
        total = len(pdfs)
        for index, pdf_path in enumerate(pdfs, 1):
            _progress(progress, index, total, f"Lendo PDFs: {index}/{total}")
            plans.append(
                _identified_plan(
                    source_name=pdf_path.name,
                    source_path=pdf_path,
                    zip_entry=None,
                    pdf_source=pdf_path,
                )
            )
    else:
        raise ValueError("selecione uma pasta ou um arquivo ZIP válido")

    if not plans:
        return AnalysisResult(source, source_kind, [])

    cnpjs = [plan.cnpj for plan in plans if plan.cnpj]
    cache = CnpjCache(cache_path)
    companies, lookup_errors = lookup_companies(
        cnpjs,
        cache=cache,
        client=client,
        progress=progress,
    )
    existing_names = (
        (path.name for path in source.iterdir() if path.is_file())
        if source_kind == "folder"
        else ()
    )
    completed = _complete_plans(plans, companies, lookup_errors, existing_names)
    return AnalysisResult(source, source_kind, completed)


def summarize(plans: Iterable[CertificatePlan]) -> dict[str, int]:
    counts = {"ready": 0, "renamed": 0, "error": 0}
    for plan in plans:
        counts[plan.status] = counts.get(plan.status, 0) + 1
    return counts


def apply_folder_renames(
    plans: Iterable[CertificatePlan],
    progress: ProgressCallback | None = None,
) -> list[CertificatePlan]:
    plan_list = list(plans)
    results: list[CertificatePlan] = []
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
                raise FileExistsError("o nome de destino passou a existir; analise novamente")
            plan.source_path.rename(target)
            results.append(
                replace(
                    plan,
                    source_path=target,
                    status="renamed",
                    message="renomeado com sucesso",
                )
            )
        except Exception as exc:
            results.append(replace(plan, status="error", message=str(exc)))
    return results


def _safe_original_name(plan: CertificatePlan, reserved: set[str]) -> str:
    source_basename = PurePosixPath(plan.source_name.replace("\\", "/")).name
    stem = Path(source_basename).stem
    try:
        safe = sanitize_filename(stem)
    except ValueError:
        safe = "certidao-nao-identificada.pdf"
    return _allocate_filename(safe, reserved)


def write_renamed_zip(
    analysis: AnalysisResult,
    output_path: Path,
    progress: ProgressCallback | None = None,
) -> Path:
    if analysis.source_kind != "zip":
        raise ValueError("a origem analisada não é um arquivo ZIP")

    output_path = output_path.expanduser().resolve()
    if output_path.exists():
        raise FileExistsError("o arquivo de saída já existe; escolha outro nome")
    if output_path == analysis.source:
        raise ValueError("o ZIP original não pode ser substituído")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temporary = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
    plans_by_entry = {plan.zip_entry: plan for plan in analysis.plans if plan.zip_entry}
    reserved: set[str] = set()

    try:
        with ZipFile(analysis.source) as source_zip, ZipFile(
            temporary,
            mode="w",
            compression=ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as destination_zip:
            source_entries = {
                info.filename: info
                for info in source_zip.infolist()
                if not info.is_dir() and info.filename.lower().endswith(".pdf")
            }
            total = len(analysis.plans)
            for index, plan in enumerate(analysis.plans, 1):
                _progress(progress, index, total, f"Gerando ZIP: {index}/{total}")
                info = source_entries.get(plan.zip_entry or "")
                if info is None:
                    raise ValueError(f"entrada não encontrada no ZIP: {plan.source_name}")

                if plan.status == "ready" and plan.target_name:
                    target_name = _allocate_filename(plan.target_name, reserved)
                else:
                    target_name = _safe_original_name(plan, reserved)

                target_info = ZipInfo(target_name, date_time=info.date_time)
                target_info.compress_type = ZIP_DEFLATED
                target_info.external_attr = info.external_attr
                with source_zip.open(info) as source_stream, destination_zip.open(
                    target_info,
                    mode="w",
                    force_zip64=True,
                ) as destination_stream:
                    shutil.copyfileobj(source_stream, destination_stream, length=1024 * 1024)

        os.replace(temporary, output_path)
        return output_path
    finally:
        if temporary.exists():
            temporary.unlink()


class CertificateRenamerApp:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.analysis: AnalysisResult | None = None

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("1220x680")
        self.root.minsize(920, 520)

        self.source_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(
            value="Escolha o ZIP das certidões ou uma pasta com PDFs."
        )
        self.progress_value = tk.DoubleVar(value=0)
        self._build_ui()

    def _build_ui(self) -> None:
        from tkinter import ttk

        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)

        ttk.Label(
            outer,
            text="Renomear certidões estaduais pela razão social",
            font=("Segoe UI", 15, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            outer,
            text=(
                "O CNPJ é localizado no PDF e confirmado pelo nome do arquivo. "
                "A primeira consulta de cada empresa requer internet."
            ),
        ).grid(row=1, column=0, sticky="w", pady=(3, 12))

        source_row = ttk.Frame(outer)
        source_row.grid(row=2, column=0, sticky="ew")
        source_row.columnconfigure(0, weight=1)
        ttk.Entry(source_row, textvariable=self.source_var).grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Button(source_row, text="Escolher ZIP", command=self.choose_zip).grid(
            row=0, column=1, padx=(0, 6)
        )
        ttk.Button(source_row, text="Escolher pasta", command=self.choose_folder).grid(
            row=0, column=2
        )

        action_row = ttk.Frame(outer)
        action_row.grid(row=3, column=0, sticky="ew", pady=10)
        action_row.columnconfigure(0, weight=1)
        self.analyze_button = ttk.Button(
            action_row,
            text="Analisar e consultar CNPJs",
            command=self.start_analysis,
        )
        self.analyze_button.grid(row=0, column=1)

        table_frame = ttk.Frame(outer)
        table_frame.grid(row=4, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table_frame,
            columns=("current", "cnpj", "company", "new", "status"),
            show="headings",
        )
        headings = {
            "current": "Arquivo atual",
            "cnpj": "CNPJ",
            "company": "Razão social",
            "new": "Novo nome",
            "status": "Situação",
        }
        widths = {"current": 270, "cnpj": 145, "company": 280, "new": 280, "status": 230}
        for column, heading in headings.items():
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=widths[column], minwidth=110)
        self.tree.grid(row=0, column=0, sticky="nsew")

        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)

        bottom = ttk.Frame(outer)
        bottom.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(
            bottom,
            variable=self.progress_value,
            maximum=100,
            length=180,
        )
        self.progress.grid(row=0, column=1, padx=10)
        self.output_button = ttk.Button(
            bottom,
            text="Gerar resultado",
            command=self.start_output,
            state="disabled",
        )
        self.output_button.grid(row=0, column=2)

    def choose_zip(self) -> None:
        from tkinter import filedialog

        selected = filedialog.askopenfilename(
            title="Escolha o arquivo ZIP com as certidões",
            filetypes=[("Arquivo ZIP", "*.zip")],
        )
        if selected:
            self.source_var.set(selected)
            self.start_analysis()

    def choose_folder(self) -> None:
        from tkinter import filedialog

        selected = filedialog.askdirectory(title="Escolha a pasta com as certidões")
        if selected:
            self.source_var.set(selected)
            self.start_analysis()

    def _set_busy(self, busy: bool) -> None:
        self.analyze_button.configure(state="disabled" if busy else "normal")
        if busy:
            self.output_button.configure(state="disabled")

    def _worker_progress(self, current: int, total: int, message: str) -> None:
        percent = (current / total * 100) if total else 0
        self.root.after(0, self._show_progress, percent, message)

    def _show_progress(self, percent: float, message: str) -> None:
        self.progress_value.set(percent)
        self.status_var.set(message)

    def start_analysis(self) -> None:
        from tkinter import messagebox

        raw_source = self.source_var.get().strip()
        if not raw_source:
            messagebox.showinfo(APP_TITLE, "Primeiro, escolha um ZIP ou uma pasta.")
            return
        source = Path(raw_source)
        if not source.exists():
            messagebox.showerror(APP_TITLE, "A origem selecionada não existe.")
            return

        self._set_busy(True)
        self.progress_value.set(0)
        self.status_var.set("Iniciando análise...")
        thread = threading.Thread(
            target=self._analysis_worker,
            args=(source,),
            daemon=True,
        )
        thread.start()

    def _analysis_worker(self, source: Path) -> None:
        try:
            result = analyze_source(source, progress=self._worker_progress)
            self.root.after(0, self._finish_analysis, result, None)
        except Exception as exc:
            self.root.after(0, self._finish_analysis, None, str(exc))

    def _finish_analysis(
        self,
        result: AnalysisResult | None,
        error: str | None,
    ) -> None:
        from tkinter import messagebox

        self._set_busy(False)
        if error or result is None:
            self.status_var.set("A análise não pôde ser concluída.")
            messagebox.showerror(APP_TITLE, error or "Erro desconhecido")
            return

        self.analysis = result
        self._refresh_table()
        counts = summarize(result.plans)
        unique_cnpjs = len({plan.cnpj for plan in result.plans if plan.cnpj})
        self.progress_value.set(100)
        self.status_var.set(
            f"{len(result.plans)} PDF(s), {unique_cnpjs} CNPJ(s) único(s): "
            f"{counts['ready']} pronto(s), {counts['error']} erro(s)."
        )
        if counts["ready"]:
            label = (
                "Gerar novo ZIP"
                if result.source_kind == "zip"
                else "Renomear arquivos"
            )
            self.output_button.configure(text=label, state="normal")
        elif not result.plans:
            messagebox.showinfo(APP_TITLE, "Nenhum PDF foi encontrado.")

    def _refresh_table(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        if not self.analysis:
            return

        for plan in self.analysis.plans:
            status = "Pronto" if plan.status == "ready" else "Erro"
            if plan.message:
                status = f"{status}: {plan.message}"
            self.tree.insert(
                "",
                "end",
                values=(
                    plan.source_name,
                    format_cnpj(plan.cnpj or ""),
                    plan.company or "-",
                    plan.target_name or "-",
                    status,
                ),
            )

    def start_output(self) -> None:
        from tkinter import filedialog, messagebox

        if not self.analysis:
            return
        ready = summarize(self.analysis.plans)["ready"]
        if not ready:
            return

        output_path: Path | None = None
        if self.analysis.source_kind == "zip":
            suggested = f"{self.analysis.source.stem}-renomeado.zip"
            selected = filedialog.asksaveasfilename(
                title="Salvar o novo ZIP",
                initialdir=str(self.analysis.source.parent),
                initialfile=suggested,
                defaultextension=".zip",
                filetypes=[("Arquivo ZIP", "*.zip")],
                confirmoverwrite=False,
            )
            if not selected:
                return
            output_path = Path(selected)
            if output_path.exists():
                messagebox.showerror(
                    APP_TITLE,
                    "Esse arquivo já existe. Escolha um nome diferente para preservar o original.",
                )
                return
            question = (
                f"Gerar um novo ZIP com {ready} certidão(ões) renomeada(s)?\n\n"
                "O arquivo compactado original permanecerá inalterado."
            )
        else:
            question = (
                f"Renomear {ready} arquivo(s) na pasta selecionada?\n\n"
                "Nenhum arquivo existente será sobrescrito."
            )

        if not messagebox.askyesno(APP_TITLE, question):
            return
        self._set_busy(True)
        self.progress_value.set(0)
        self.status_var.set("Gerando resultado...")
        thread = threading.Thread(
            target=self._output_worker,
            args=(output_path,),
            daemon=True,
        )
        thread.start()

    def _output_worker(self, output_path: Path | None) -> None:
        try:
            if not self.analysis:
                raise ValueError("a análise não está mais disponível")
            if self.analysis.source_kind == "zip":
                if output_path is None:
                    raise ValueError("o arquivo de saída não foi informado")
                result_path = write_renamed_zip(
                    self.analysis,
                    output_path,
                    progress=self._worker_progress,
                )
                self.root.after(0, self._finish_output, result_path, None)
            else:
                plans = apply_folder_renames(
                    self.analysis.plans,
                    progress=self._worker_progress,
                )
                self.analysis = replace(self.analysis, plans=plans)
                self.root.after(0, self._finish_output, None, None)
        except Exception as exc:
            self.root.after(0, self._finish_output, None, str(exc))

    def _finish_output(self, result_path: Path | None, error: str | None) -> None:
        from tkinter import messagebox

        self._set_busy(False)
        self.output_button.configure(state="disabled")
        if error:
            self.status_var.set("O resultado não pôde ser gerado.")
            messagebox.showerror(APP_TITLE, error)
            return

        self.progress_value.set(100)
        if result_path:
            self.status_var.set(f"Novo ZIP criado: {result_path.name}")
            messagebox.showinfo(
                APP_TITLE,
                f"Novo ZIP criado com sucesso:\n{result_path}\n\n"
                "O arquivo original não foi alterado.",
            )
        else:
            self._refresh_table()
            counts = summarize(self.analysis.plans if self.analysis else [])
            self.status_var.set(
                f"Concluído: {counts['renamed']} renomeado(s), {counts['error']} erro(s)."
            )
            messagebox.showinfo(APP_TITLE, "Arquivos renomeados com sucesso.")

    def run(self) -> None:
        self.root.mainloop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Renomeia certidões estaduais usando a razão social consultada pelo CNPJ."
    )
    parser.add_argument(
        "fonte",
        nargs="?",
        type=Path,
        help="arquivo ZIP ou pasta com os PDFs; sem este argumento, abre a interface",
    )
    parser.add_argument("--cache", type=Path, help="arquivo de cache alternativo")
    parser.add_argument("--saida", type=Path, help="novo ZIP de saída")
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="gera o ZIP ou renomeia a pasta; sem esta opção, apenas analisa",
    )
    return parser


def run_cli(args: argparse.Namespace) -> int:
    result = analyze_source(args.fonte, cache_path=args.cache)
    counts = summarize(result.plans)
    print(
        f"{len(result.plans)} PDF(s): {counts['ready']} pronto(s), "
        f"{counts['error']} erro(s)."
    )
    if args.aplicar:
        if result.source_kind == "zip":
            output = args.saida or result.source.with_name(
                f"{result.source.stem}-renomeado.zip"
            )
            write_renamed_zip(result, output)
            print(f"Novo ZIP: {output}")
        else:
            applied = apply_folder_renames(result.plans)
            counts = summarize(applied)
            print(f"{counts['renamed']} arquivo(s) renomeado(s).")
    return 1 if counts["error"] else 0


def main() -> int:
    args = build_parser().parse_args()
    if args.fonte:
        try:
            return run_cli(args)
        except Exception as exc:
            print(f"Erro: {exc}", file=sys.stderr)
            return 1
    try:
        CertificateRenamerApp().run()
        return 0
    except Exception as exc:
        print(f"Não foi possível abrir o programa: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
