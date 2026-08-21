from __future__ import annotations

import argparse
import os
import sys
import threading
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable
from zipfile import ZipFile

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from pypdf import PdfReader

from certidoes_estaduais import (
    AnalysisResult as CertificateAnalysis,
    CertificatePlan,
    analyze_source as analyze_certificates,
    apply_folder_renames as apply_certificate_folder_renames,
    format_cnpj,
    summarize as summarize_certificates,
    write_renamed_zip as write_certificate_zip,
)
from parcelamentos import (
    analyze_installment_source,
    apply_installment_folder_renames,
    create_installment_panel_class,
    summarize_installments,
    write_installment_zip,
)
from renomeador_pdfs import (
    MAX_FILENAME_LENGTH,
    extract_company_name_from_text,
    sanitize_filename,
)


APP_TITLE = "Facilita Fiscal - Renomeador de PDFs"
ProgressCallback = Callable[[int, int, str], None]

APP_BACKGROUND = "#EEF3F9"
HEADER_BACKGROUND = "#071B3D"
HEADER_CARD = "#102A52"
SURFACE = "#FFFFFF"
SURFACE_MUTED = "#F7F9FC"
NAVY = "#12305A"
TEXT = "#1D2B3F"
TEXT_MUTED = "#637188"
BLUE = "#1557D5"
BLUE_DARK = "#0D43AE"
BLUE_LIGHT = "#E8F1FF"
GREEN = "#169B62"
GREEN_DARK = "#0E7A4B"
GREEN_LIGHT = "#EAF8F1"
BORDER = "#D8E1EC"
ERROR = "#B42318"
ERROR_LIGHT = "#FFF1F0"


def resource_path(relative_path: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative_path


def configure_visual_styles(root: tk.Tk) -> None:
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure(".", font=("Segoe UI", 10), foreground=TEXT)
    style.configure("App.TFrame", background=APP_BACKGROUND)
    style.configure("Workspace.TFrame", background=APP_BACKGROUND)
    style.configure(
        "Card.TFrame",
        background=SURFACE,
        bordercolor=BORDER,
        borderwidth=1,
        relief="solid",
    )
    style.configure("CardInner.TFrame", background=SURFACE)

    style.configure(
        "HeroEyebrow.TLabel",
        background=BLUE_LIGHT,
        foreground=BLUE,
        font=("Segoe UI", 9, "bold"),
        padding=(10, 5),
    )
    style.configure(
        "HeroTitle.TLabel",
        background=SURFACE,
        foreground=NAVY,
        font=("Segoe UI", 18, "bold"),
    )
    style.configure(
        "HeroDescription.TLabel",
        background=SURFACE,
        foreground=TEXT_MUTED,
        font=("Segoe UI", 10),
    )
    style.configure(
        "SectionTitle.TLabel",
        background=SURFACE,
        foreground=TEXT,
        font=("Segoe UI", 11, "bold"),
    )
    style.configure(
        "Caption.TLabel",
        background=SURFACE,
        foreground=TEXT_MUTED,
        font=("Segoe UI", 9),
    )
    style.configure(
        "StatusDot.TLabel",
        background=SURFACE,
        foreground=GREEN,
        font=("Segoe UI", 12, "bold"),
    )
    style.configure(
        "Status.TLabel",
        background=SURFACE,
        foreground=TEXT_MUTED,
        font=("Segoe UI", 9),
    )

    style.configure(
        "Modern.TEntry",
        fieldbackground=SURFACE_MUTED,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        insertcolor=BLUE,
        padding=(10, 9),
    )
    style.map(
        "Modern.TEntry",
        bordercolor=[("focus", BLUE)],
        lightcolor=[("focus", BLUE)],
        darkcolor=[("focus", BLUE)],
    )

    button_common = {
        "font": ("Segoe UI", 9, "bold"),
        "padding": (14, 9),
        "borderwidth": 1,
        "relief": "flat",
    }
    style.configure(
        "Primary.TButton",
        **button_common,
        background=BLUE,
        foreground="#FFFFFF",
        bordercolor=BLUE,
        lightcolor=BLUE,
        darkcolor=BLUE,
    )
    style.map(
        "Primary.TButton",
        background=[
            ("disabled", "#D9E1EC"),
            ("pressed", BLUE_DARK),
            ("active", BLUE_DARK),
        ],
        bordercolor=[
            ("disabled", "#D9E1EC"),
            ("pressed", BLUE_DARK),
            ("active", BLUE_DARK),
        ],
        foreground=[("disabled", "#A8B3C3"), ("!disabled", "#FFFFFF")],
    )
    style.configure(
        "Secondary.TButton",
        **button_common,
        background=SURFACE,
        foreground=BLUE,
        bordercolor="#B9C9E2",
        lightcolor="#B9C9E2",
        darkcolor="#B9C9E2",
    )
    style.map(
        "Secondary.TButton",
        background=[
            ("disabled", "#F1F4F8"),
            ("pressed", BLUE_LIGHT),
            ("active", BLUE_LIGHT),
        ],
        bordercolor=[
            ("disabled", "#D9E1EC"),
            ("pressed", BLUE),
            ("active", BLUE),
        ],
        foreground=[("disabled", "#A8B3C3"), ("!disabled", BLUE)],
    )
    style.configure(
        "Success.TButton",
        **button_common,
        background=GREEN,
        foreground="#FFFFFF",
        bordercolor=GREEN,
        lightcolor=GREEN,
        darkcolor=GREEN,
    )
    style.map(
        "Success.TButton",
        background=[
            ("disabled", "#D9E1EC"),
            ("pressed", GREEN_DARK),
            ("active", GREEN_DARK),
        ],
        bordercolor=[
            ("disabled", "#D9E1EC"),
            ("pressed", GREEN_DARK),
            ("active", GREEN_DARK),
        ],
        foreground=[("disabled", "#A8B3C3"), ("!disabled", "#FFFFFF")],
    )

    style.configure(
        "App.TNotebook",
        background=APP_BACKGROUND,
        borderwidth=0,
        tabmargins=(0, 0, 0, 0),
    )
    style.configure(
        "App.TNotebook.Tab",
        background="#DFE7F2",
        foreground=TEXT_MUTED,
        padding=(22, 11),
        font=("Segoe UI", 10, "bold"),
        borderwidth=0,
    )
    style.map(
        "App.TNotebook.Tab",
        background=[("selected", SURFACE), ("active", BLUE_LIGHT)],
        foreground=[("selected", BLUE), ("active", BLUE_DARK)],
        padding=[("selected", (22, 12))],
    )

    style.configure(
        "Modern.Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        borderwidth=0,
        rowheight=32,
        font=("Segoe UI", 9),
    )
    style.map(
        "Modern.Treeview",
        background=[("selected", "#DCEAFF")],
        foreground=[("selected", NAVY)],
    )
    style.configure(
        "Modern.Treeview.Heading",
        background="#E8EEF7",
        foreground=NAVY,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=(9, 9),
        relief="flat",
        font=("Segoe UI", 9, "bold"),
    )
    style.map(
        "Modern.Treeview.Heading",
        background=[("active", "#DCE7F5")],
        foreground=[("active", BLUE_DARK)],
    )
    style.configure(
        "Modern.Vertical.TScrollbar",
        background="#C4D0E0",
        troughcolor=SURFACE,
        bordercolor=SURFACE,
        arrowcolor=TEXT_MUTED,
    )
    style.configure(
        "Modern.Horizontal.TScrollbar",
        background="#C4D0E0",
        troughcolor=SURFACE,
        bordercolor=SURFACE,
        arrowcolor=TEXT_MUTED,
    )
    style.configure(
        "Modern.Horizontal.TProgressbar",
        troughcolor="#DFE7F1",
        background=GREEN,
        bordercolor="#DFE7F1",
        lightcolor=GREEN,
        darkcolor=GREEN,
        thickness=8,
    )


@dataclass(frozen=True)
class SituationPlan:
    source_name: str
    source_path: Path | None
    zip_entry: str | None
    company: str | None
    target_name: str | None
    status: str
    message: str = ""


@dataclass(frozen=True)
class SituationAnalysis:
    source: Path
    source_kind: str
    plans: list[SituationPlan]


def extract_company_from_pdf_source(
    pdf_source: bytes | Path,
    max_pages: int = 3,
) -> str:
    source = BytesIO(pdf_source) if isinstance(pdf_source, bytes) else str(pdf_source)
    try:
        reader = PdfReader(source)
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise ValueError("o PDF está protegido por senha")
        for page in reader.pages[:max_pages]:
            company = extract_company_name_from_text(page.extract_text() or "")
            if company:
                return company
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"não foi possível ler o PDF: {exc}") from exc
    raise ValueError("a linha com CPF/CNPJ e nome não foi encontrada")


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


def _initial_situation_plan(
    source_name: str,
    source_path: Path | None,
    zip_entry: str | None,
    pdf_source: bytes | Path,
) -> SituationPlan:
    try:
        company = extract_company_from_pdf_source(pdf_source)
        return SituationPlan(
            source_name=source_name,
            source_path=source_path,
            zip_entry=zip_entry,
            company=company,
            target_name=sanitize_filename(company),
            status="identified",
        )
    except Exception as exc:
        return SituationPlan(
            source_name=source_name,
            source_path=source_path,
            zip_entry=zip_entry,
            company=None,
            target_name=None,
            status="error",
            message=str(exc),
        )


def _complete_situation_plans(
    plans: list[SituationPlan],
    existing_names: Iterable[str] = (),
) -> list[SituationPlan]:
    reserved = {name.casefold() for name in existing_names}
    completed: list[SituationPlan] = []

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


def analyze_situation_source(
    source: Path,
    progress: ProgressCallback | None = None,
) -> SituationAnalysis:
    source = source.expanduser().resolve()
    plans: list[SituationPlan] = []

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
                    _initial_situation_plan(
                        source_name=info.filename,
                        source_path=None,
                        zip_entry=info.filename,
                        pdf_source=archive.read(info),
                    )
                )
        completed = _complete_situation_plans(plans)
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
                _initial_situation_plan(
                    source_name=pdf_path.name,
                    source_path=pdf_path,
                    zip_entry=None,
                    pdf_source=pdf_path,
                )
            )
        existing_names = (path.name for path in source.iterdir() if path.is_file())
        completed = _complete_situation_plans(plans, existing_names)
    else:
        raise ValueError("selecione uma pasta ou um arquivo ZIP válido")

    return SituationAnalysis(source=source, source_kind=source_kind, plans=completed)


def summarize_situation(plans: Iterable[SituationPlan]) -> dict[str, int]:
    counts = {"ready": 0, "renamed": 0, "already_named": 0, "error": 0}
    for plan in plans:
        counts[plan.status] = counts.get(plan.status, 0) + 1
    return counts


def apply_situation_folder_renames(
    plans: Iterable[SituationPlan],
    progress: ProgressCallback | None = None,
) -> list[SituationPlan]:
    plan_list = list(plans)
    results: list[SituationPlan] = []
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


def write_situation_zip(
    analysis: SituationAnalysis,
    output_path: Path,
    progress: ProgressCallback | None = None,
) -> Path:
    converted = [
        CertificatePlan(
            source_name=plan.source_name,
            source_path=None,
            zip_entry=plan.zip_entry,
            cnpj=None,
            cnpj_origin=None,
            company=plan.company,
            target_name=plan.target_name,
            status=plan.status,
            message=plan.message,
        )
        for plan in analysis.plans
    ]
    certificate_analysis = CertificateAnalysis(
        source=analysis.source,
        source_kind="zip",
        plans=converted,
    )
    return write_certificate_zip(certificate_analysis, output_path, progress)


class ServicePanel(ttk.Frame):
    def __init__(
        self,
        parent: ttk.Notebook,
        title: str,
        description: str,
        category: str,
        columns: tuple[str, ...],
        headings: dict[str, str],
        widths: dict[str, int],
    ) -> None:
        super().__init__(
            parent,
            padding=(18, 16, 18, 18),
            style="Workspace.TFrame",
        )
        self.analysis: object | None = None
        self.source_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(
            value="Escolha um ZIP ou uma pasta que contenha os PDFs."
        )
        self.progress_value = tk.DoubleVar(value=0)
        self._build_ui(title, description, category, columns, headings, widths)

    def _build_ui(
        self,
        title: str,
        description: str,
        category: str,
        columns: tuple[str, ...],
        headings: dict[str, str],
        widths: dict[str, int],
    ) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        intro = ttk.Frame(self, padding=(18, 14), style="Card.TFrame")
        intro.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        intro.columnconfigure(0, weight=1)
        ttk.Label(
            intro,
            text=category.upper(),
            style="HeroEyebrow.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            intro,
            text=title,
            style="HeroTitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(9, 2))
        ttk.Label(
            intro,
            text=description,
            style="HeroDescription.TLabel",
            wraplength=1020,
        ).grid(row=2, column=0, sticky="w")

        source_row = ttk.Frame(self, padding=(16, 13), style="Card.TFrame")
        source_row.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        source_row.columnconfigure(0, weight=1)
        ttk.Label(
            source_row,
            text="Selecione a origem dos documentos",
            style="SectionTitle.TLabel",
        ).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(
            source_row,
            text=(
                "Escolha um arquivo ZIP ou uma pasta. "
                "A análise começará automaticamente."
            ),
            style="Caption.TLabel",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 10))
        ttk.Entry(
            source_row,
            textvariable=self.source_var,
            style="Modern.TEntry",
        ).grid(row=2, column=0, sticky="ew", padx=(0, 10))
        self.zip_button = ttk.Button(
            source_row,
            text="Selecionar ZIP",
            command=self.choose_zip,
            style="Secondary.TButton",
        )
        self.zip_button.grid(row=2, column=1, padx=(0, 8))
        self.folder_button = ttk.Button(
            source_row,
            text="Selecionar pasta",
            command=self.choose_folder,
            style="Secondary.TButton",
        )
        self.folder_button.grid(row=2, column=2, padx=(0, 8))
        self.analyze_button = ttk.Button(
            source_row,
            text="Analisar documentos",
            command=self.start_analysis,
            style="Primary.TButton",
        )
        self.analyze_button.grid(row=2, column=3)

        table_card = ttk.Frame(self, padding=(14, 12), style="Card.TFrame")
        table_card.grid(row=2, column=0, sticky="nsew")
        table_card.columnconfigure(0, weight=1)
        table_card.rowconfigure(1, weight=1)

        table_header = ttk.Frame(table_card, style="CardInner.TFrame")
        table_header.grid(row=0, column=0, sticky="ew", pady=(0, 9))
        table_header.columnconfigure(0, weight=1)
        ttk.Label(
            table_header,
            text="Prévia dos arquivos",
            style="SectionTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            table_header,
            text="Confira os dados encontrados antes de gerar o resultado.",
            style="Caption.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        table_frame = ttk.Frame(table_card, style="CardInner.TFrame")
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            style="Modern.Treeview",
        )
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=100)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.tag_configure("even", background=SURFACE)
        self.tree.tag_configure("odd", background="#F8FAFD")
        self.tree.tag_configure(
            "success",
            background=GREEN_LIGHT,
            foreground="#17633F",
        )
        self.tree.tag_configure(
            "error",
            background=ERROR_LIGHT,
            foreground=ERROR,
        )
        self.tree.tag_configure(
            "neutral",
            background=BLUE_LIGHT,
            foreground=NAVY,
        )
        vertical = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self.tree.yview,
            style="Modern.Vertical.TScrollbar",
        )
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=self.tree.xview,
            style="Modern.Horizontal.TScrollbar",
        )
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )

        bottom = ttk.Frame(self, padding=(14, 10), style="Card.TFrame")
        bottom.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        bottom.columnconfigure(1, weight=1)
        ttk.Label(
            bottom,
            text="●",
            style="StatusDot.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(
            bottom,
            textvariable=self.status_var,
            style="Status.TLabel",
        ).grid(row=0, column=1, sticky="w")
        self.progress = ttk.Progressbar(
            bottom,
            variable=self.progress_value,
            maximum=100,
            length=190,
            style="Modern.Horizontal.TProgressbar",
        )
        self.progress.grid(row=0, column=2, padx=12)
        self.output_button = ttk.Button(
            bottom,
            text="Gerar resultado",
            command=self.start_output,
            state="disabled",
            style="Success.TButton",
        )
        self.output_button.grid(row=0, column=3)
    def choose_zip(self) -> None:
        selected = filedialog.askopenfilename(
            title="Escolha o arquivo ZIP com os PDFs",
            filetypes=[("Arquivo ZIP", "*.zip")],
        )
        if selected:
            self.source_var.set(selected)
            self.start_analysis()

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(title="Escolha a pasta com os PDFs")
        if selected:
            self.source_var.set(selected)
            self.start_analysis()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.zip_button.configure(state=state)
        self.folder_button.configure(state=state)
        self.analyze_button.configure(state=state)
        self.output_button.configure(state="disabled")

    def _worker_progress(self, current: int, total: int, message: str) -> None:
        percent = (current / total * 100) if total else 0
        self.after(0, self._show_progress, percent, message)

    def _show_progress(self, percent: float, message: str) -> None:
        self.progress_value.set(percent)
        self.status_var.set(message)

    def start_analysis(self) -> None:
        raw_source = self.source_var.get().strip()
        if not raw_source:
            messagebox.showinfo(APP_TITLE, "Primeiro, escolha um ZIP ou uma pasta.")
            return
        source = Path(raw_source)
        is_valid = source.is_dir() or (
            source.is_file() and source.suffix.lower() == ".zip"
        )
        if not is_valid:
            messagebox.showerror(APP_TITLE, "A origem selecionada não é válida.")
            return

        self.analysis = None
        self._clear_tree()
        self._set_busy(True)
        self.progress_value.set(0)
        self.status_var.set("Iniciando análise...")
        threading.Thread(
            target=self._analysis_worker,
            args=(source,),
            daemon=True,
        ).start()

    def _analysis_worker(self, source: Path) -> None:
        try:
            result = self.perform_analysis(source, self._worker_progress)
            self.after(0, self._finish_analysis, result, None)
        except Exception as exc:
            self.after(0, self._finish_analysis, None, str(exc))

    def _finish_analysis(self, result: object | None, error: str | None) -> None:
        self._set_busy(False)
        if error or result is None:
            self.status_var.set("A análise não pôde ser concluída.")
            messagebox.showerror(APP_TITLE, error or "Erro desconhecido")
            return
        self.analysis = result
        self.refresh_tree()
        self.progress_value.set(100)
        self.status_var.set(self.analysis_summary())
        ready = self.ready_count()
        if ready:
            kind = getattr(self.analysis, "source_kind", "folder")
            label = "Gerar novo ZIP" if kind == "zip" else "Renomear arquivos"
            self.output_button.configure(text=label, state="normal")
        if self.plan_count() == 0:
            messagebox.showinfo(APP_TITLE, "Nenhum PDF foi encontrado.")

    def _clear_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

    def refresh_tree(self) -> None:
        self._clear_tree()
        for index, values in enumerate(self.table_rows()):
            status = str(values[-1]).casefold() if values else ""
            if status.startswith("erro"):
                tag = "error"
            elif status.startswith(("pronto", "renomeado")):
                tag = "success"
            elif status.startswith("já"):
                tag = "neutral"
            else:
                tag = "even" if index % 2 == 0 else "odd"
            self.tree.insert("", "end", values=values, tags=(tag,))

    def start_output(self) -> None:
        if not self.analysis or not self.ready_count():
            return
        source = getattr(self.analysis, "source")
        source_kind = getattr(self.analysis, "source_kind")
        output_path: Path | None = None
        if source_kind == "zip":
            selected = filedialog.asksaveasfilename(
                title="Salvar o novo ZIP",
                initialdir=str(source.parent),
                initialfile=f"{source.stem}-renomeado.zip",
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
                    "Esse arquivo já existe. Escolha outro nome para preservar o original.",
                )
                return
            question = (
                f"Gerar um novo ZIP com {self.ready_count()} PDF(s) renomeado(s)?\n\n"
                "O ZIP original permanecerá inalterado."
            )
        else:
            question = (
                f"Renomear {self.ready_count()} PDF(s) na pasta selecionada?\n\n"
                "Nenhum arquivo existente será sobrescrito."
            )
        if not messagebox.askyesno(APP_TITLE, question):
            return

        self._set_busy(True)
        self.progress_value.set(0)
        self.status_var.set("Gerando resultado...")
        threading.Thread(
            target=self._output_worker,
            args=(output_path,),
            daemon=True,
        ).start()

    def _output_worker(self, output_path: Path | None) -> None:
        try:
            updated, written_path = self.perform_output(
                output_path,
                self._worker_progress,
            )
            self.after(0, self._finish_output, updated, written_path, None)
        except Exception as exc:
            self.after(0, self._finish_output, None, None, str(exc))

    def _finish_output(
        self,
        updated: object | None,
        written_path: Path | None,
        error: str | None,
    ) -> None:
        self._set_busy(False)
        if error:
            self.status_var.set("O resultado não pôde ser gerado.")
            self.output_button.configure(state="normal")
            messagebox.showerror(APP_TITLE, error)
            return
        if updated is not None:
            self.analysis = updated
        self.progress_value.set(100)
        self.refresh_tree()
        if written_path:
            self.status_var.set(f"Novo ZIP criado: {written_path.name}")
            messagebox.showinfo(
                APP_TITLE,
                f"Novo ZIP criado com sucesso:\n{written_path}\n\n"
                "O arquivo original não foi alterado.",
            )
        else:
            self.status_var.set(self.output_summary())
            messagebox.showinfo(APP_TITLE, "Arquivos renomeados com sucesso.")

    def perform_analysis(
        self,
        source: Path,
        progress: ProgressCallback,
    ) -> object:
        raise NotImplementedError

    def perform_output(
        self,
        output_path: Path | None,
        progress: ProgressCallback,
    ) -> tuple[object, Path | None]:
        raise NotImplementedError

    def table_rows(self) -> Iterable[tuple[str, ...]]:
        raise NotImplementedError

    def ready_count(self) -> int:
        raise NotImplementedError

    def plan_count(self) -> int:
        raise NotImplementedError

    def analysis_summary(self) -> str:
        raise NotImplementedError

    def output_summary(self) -> str:
        raise NotImplementedError


class SituationPanel(ServicePanel):
    def __init__(self, parent: ttk.Notebook) -> None:
        super().__init__(
            parent,
            title="Renomear relatórios de situação fiscal",
            description=(
                "O nome da empresa ou pessoa é lido diretamente no relatório. "
                "Este serviço não precisa de internet."
            ),
            category="Leitura direta do PDF",
            columns=("current", "company", "new", "status"),
            headings={
                "current": "Arquivo atual",
                "company": "Nome encontrado",
                "new": "Novo nome",
                "status": "Situação",
            },
            widths={"current": 300, "company": 300, "new": 300, "status": 230},
        )

    @property
    def result(self) -> SituationAnalysis:
        assert isinstance(self.analysis, SituationAnalysis)
        return self.analysis

    def perform_analysis(
        self,
        source: Path,
        progress: ProgressCallback,
    ) -> SituationAnalysis:
        return analyze_situation_source(source, progress)

    def perform_output(
        self,
        output_path: Path | None,
        progress: ProgressCallback,
    ) -> tuple[SituationAnalysis, Path | None]:
        if self.result.source_kind == "zip":
            if output_path is None:
                raise ValueError("o arquivo de saída não foi informado")
            written = write_situation_zip(self.result, output_path, progress)
            return self.result, written
        plans = apply_situation_folder_renames(self.result.plans, progress)
        return replace(self.result, plans=plans), None

    def table_rows(self) -> Iterable[tuple[str, ...]]:
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
                plan.company or "-",
                plan.target_name or "-",
                status,
            )

    def ready_count(self) -> int:
        return summarize_situation(self.result.plans)["ready"]

    def plan_count(self) -> int:
        return len(self.result.plans)

    def analysis_summary(self) -> str:
        counts = summarize_situation(self.result.plans)
        return (
            f"{len(self.result.plans)} PDF(s): {counts['ready']} para renomear, "
            f"{counts['already_named']} já correto(s), {counts['error']} com erro."
        )

    def output_summary(self) -> str:
        counts = summarize_situation(self.result.plans)
        return (
            f"Concluído: {counts['renamed']} renomeado(s), "
            f"{counts['already_named']} já correto(s), {counts['error']} erro(s)."
        )


class CertificatePanel(ServicePanel):
    def __init__(self, parent: ttk.Notebook) -> None:
        super().__init__(
            parent,
            title="Renomear certidões estaduais pela razão social",
            description=(
                "O CNPJ é localizado no PDF ou no nome técnico do arquivo. "
                "A primeira consulta de cada empresa requer internet."
            ),
            category="Consulta pela razão social",
            columns=("current", "cnpj", "company", "new", "status"),
            headings={
                "current": "Arquivo atual",
                "cnpj": "CNPJ",
                "company": "Razão social",
                "new": "Novo nome",
                "status": "Situação",
            },
            widths={
                "current": 270,
                "cnpj": 145,
                "company": 280,
                "new": 280,
                "status": 230,
            },
        )

    @property
    def result(self) -> CertificateAnalysis:
        assert isinstance(self.analysis, CertificateAnalysis)
        return self.analysis

    def perform_analysis(
        self,
        source: Path,
        progress: ProgressCallback,
    ) -> CertificateAnalysis:
        return analyze_certificates(source, progress=progress)

    def perform_output(
        self,
        output_path: Path | None,
        progress: ProgressCallback,
    ) -> tuple[CertificateAnalysis, Path | None]:
        if self.result.source_kind == "zip":
            if output_path is None:
                raise ValueError("o arquivo de saída não foi informado")
            written = write_certificate_zip(self.result, output_path, progress)
            return self.result, written
        plans = apply_certificate_folder_renames(self.result.plans, progress)
        return replace(self.result, plans=plans), None

    def table_rows(self) -> Iterable[tuple[str, ...]]:
        labels = {"ready": "Pronto", "renamed": "Renomeado", "error": "Erro"}
        for plan in self.result.plans:
            status = labels.get(plan.status, plan.status)
            if plan.message:
                status = f"{status}: {plan.message}"
            yield (
                plan.source_name,
                format_cnpj(plan.cnpj or ""),
                plan.company or "-",
                plan.target_name or "-",
                status,
            )

    def ready_count(self) -> int:
        return summarize_certificates(self.result.plans)["ready"]

    def plan_count(self) -> int:
        return len(self.result.plans)

    def analysis_summary(self) -> str:
        counts = summarize_certificates(self.result.plans)
        unique = len({plan.cnpj for plan in self.result.plans if plan.cnpj})
        return (
            f"{len(self.result.plans)} PDF(s), {unique} CNPJ(s) único(s): "
            f"{counts['ready']} pronto(s), {counts['error']} erro(s)."
        )

    def output_summary(self) -> str:
        counts = summarize_certificates(self.result.plans)
        return (
            f"Concluído: {counts['renamed']} renomeado(s), "
            f"{counts['error']} erro(s)."
        )


InstallmentPanel = create_installment_panel_class(ServicePanel)


class FacilitaFiscalApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        icon_path = resource_path("assets/facilita_fiscal_icon.ico")
        if icon_path.exists():
            try:
                self.root.iconbitmap(default=str(icon_path))
            except tk.TclError:
                pass
        self.root.geometry("1280x760")
        self.root.minsize(980, 620)
        self.root.configure(background=APP_BACKGROUND)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        configure_visual_styles(self.root)

        header = tk.Frame(
            self.root,
            background=HEADER_BACKGROUND,
            height=106,
        )
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(1, weight=1)

        self.brand_icon: tk.PhotoImage | None = None
        logo_path = resource_path("assets/facilita_fiscal_icon.png")
        if logo_path.exists():
            try:
                original = tk.PhotoImage(file=str(logo_path))
                scale = max(1, original.width() // 58)
                self.brand_icon = original.subsample(scale, scale)
            except tk.TclError:
                self.brand_icon = None

        if self.brand_icon:
            tk.Label(
                header,
                image=self.brand_icon,
                background=HEADER_BACKGROUND,
                borderwidth=0,
            ).grid(
                row=0,
                column=0,
                rowspan=2,
                padx=(24, 14),
                pady=18,
            )
        else:
            tk.Label(
                header,
                text="F",
                background=GREEN,
                foreground="#FFFFFF",
                font=("Segoe UI", 22, "bold"),
                padx=15,
                pady=7,
            ).grid(
                row=0,
                column=0,
                rowspan=2,
                padx=(24, 14),
                pady=18,
            )

        tk.Label(
            header,
            text="Facilita Fiscal",
            background=HEADER_BACKGROUND,
            foreground="#FFFFFF",
            font=("Segoe UI", 21, "bold"),
        ).grid(row=0, column=1, sticky="sw", pady=(19, 0))
        tk.Label(
            header,
            text="Automação para documentos fiscais",
            background=HEADER_BACKGROUND,
            foreground="#AFC0DA",
            font=("Segoe UI", 10),
        ).grid(row=1, column=1, sticky="nw", pady=(1, 20))

        header_message = tk.Frame(
            header,
            background=HEADER_CARD,
            highlightbackground="#1B3E70",
            highlightthickness=1,
        )
        header_message.grid(
            row=0,
            column=2,
            rowspan=2,
            padx=(18, 24),
            pady=22,
        )
        tk.Label(
            header_message,
            text="ORGANIZAÇÃO FISCAL",
            background=HEADER_CARD,
            foreground="#69D7A7",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", padx=16, pady=(10, 1))
        tk.Label(
            header_message,
            text="Escolha um serviço e deixe o sistema cuidar dos arquivos.",
            background=HEADER_CARD,
            foreground="#E7EEF8",
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=16, pady=(0, 10))

        outer = ttk.Frame(
            self.root,
            padding=(18, 14, 18, 18),
            style="App.TFrame",
        )
        outer.grid(row=1, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(outer, style="App.TNotebook")
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.situation_panel = SituationPanel(self.notebook)
        self.certificate_panel = CertificatePanel(self.notebook)
        self.installment_panel = InstallmentPanel(self.notebook)
        self.notebook.add(self.situation_panel, text="Situação Fiscal")
        self.notebook.add(self.certificate_panel, text="Certidões Estaduais")
        self.notebook.add(
            self.installment_panel,
            text="Parcelamentos (DARF/DAS)",
        )
    def run(self) -> None:
        self.root.mainloop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Renomeia relatórios, certidões estaduais e parcelamentos DARF/DAS."
        )
    )
    parser.add_argument(
        "fonte",
        nargs="?",
        type=Path,
        help="arquivo ZIP ou pasta; sem este argumento, abre a interface",
    )
    parser.add_argument(
        "--servico",
        choices=("situacao", "certidao", "parcelamento"),
        default="certidao",
    )
    parser.add_argument("--cache", type=Path, help="cache alternativo para CNPJs")
    parser.add_argument("--saida", type=Path, help="novo ZIP de saída")
    parser.add_argument("--aplicar", action="store_true")
    return parser


def run_cli(args: argparse.Namespace) -> int:
    if args.servico == "situacao":
        result = analyze_situation_source(args.fonte)
        counts = summarize_situation(result.plans)
        if args.aplicar:
            if result.source_kind == "zip":
                output = args.saida or result.source.with_name(
                    f"{result.source.stem}-renomeado.zip"
                )
                write_situation_zip(result, output)
            else:
                result = replace(
                    result,
                    plans=apply_situation_folder_renames(result.plans),
                )
                counts = summarize_situation(result.plans)
        print(
            f"{len(result.plans)} PDF(s): {counts['ready']} pronto(s), "
            f"{counts['error']} erro(s)."
        )
        return 1 if counts["error"] else 0

    if args.servico == "parcelamento":
        result = analyze_installment_source(args.fonte)
        counts = summarize_installments(result.plans)
        if args.aplicar:
            if result.source_kind == "zip":
                output = args.saida or result.source.with_name(
                    f"{result.source.stem}-renomeado.zip"
                )
                write_installment_zip(result, output)
            else:
                result = replace(
                    result,
                    plans=apply_installment_folder_renames(result.plans),
                )
                counts = summarize_installments(result.plans)
        print(
            f"{len(result.plans)} PDF(s): {counts['ready']} pronto(s), "
            f"{counts['error']} erro(s)."
        )
        return 1 if counts["error"] else 0

    result = analyze_certificates(args.fonte, cache_path=args.cache)
    counts = summarize_certificates(result.plans)
    if args.aplicar:
        if result.source_kind == "zip":
            output = args.saida or result.source.with_name(
                f"{result.source.stem}-renomeado.zip"
            )
            write_certificate_zip(result, output)
        else:
            result = replace(
                result,
                plans=apply_certificate_folder_renames(result.plans),
            )
            counts = summarize_certificates(result.plans)
    print(
        f"{len(result.plans)} PDF(s): {counts['ready']} pronto(s), "
        f"{counts['error']} erro(s)."
    )
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
        FacilitaFiscalApp().run()
        return 0
    except Exception as exc:
        print(f"Não foi possível abrir o programa: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
