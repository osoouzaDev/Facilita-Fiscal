from __future__ import annotations

import argparse
import os
import re
import sys
import threading
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable


APP_TITLE = "Renomeador de Relatórios Fiscais"
MAX_FILENAME_LENGTH = 200

INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WHITESPACE = re.compile(r"\s+")
IDENTIFIER_WITH_NAME = re.compile(
    r"^\s*(?:"
    r"CNPJ\s*:\s*\d{2}\s*\.?\s*\d{3}\s*\.?\s*\d{3}"
    r"(?:\s*/?\s*\d{4}\s*-?\s*\d{2})?"
    r"|CPF\s*:\s*\d{3}\s*\.?\s*\d{3}\s*\.?\s*\d{3}\s*-?\s*\d{2}"
    r")"
    r"\s*[-\u2013\u2014]\s*(?P<company>.+?)\s*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


@dataclass(frozen=True)
class RenamePlan:
    source: Path
    target: Path | None
    company: str | None
    status: str
    message: str = ""


def extract_company_name_from_text(text: str) -> str | None:
    """Extrai a razão social da linha de identificação no cabeçalho."""
    match = IDENTIFIER_WITH_NAME.search(text)
    if not match:
        return None

    company = WHITESPACE.sub(" ", match.group("company")).strip()
    return company or None


def extract_company_name_from_pdf(pdf_path: Path, max_pages: int = 3) -> str:
    """Lê as primeiras páginas do PDF e retorna a razão social."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "A biblioteca pypdf não está instalada. Execute: "
            "py -m pip install -r requirements.txt"
        ) from exc

    try:
        reader = PdfReader(str(pdf_path))
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise ValueError("o PDF está protegido por senha")

        for page in reader.pages[:max_pages]:
            company = extract_company_name_from_text(page.extract_text() or "")
            if company:
                return company
    except Exception as exc:
        if isinstance(exc, (RuntimeError, ValueError)):
            raise
        raise ValueError(f"não foi possível ler o PDF: {exc}") from exc

    raise ValueError("a linha com CPF/CNPJ e nome não foi encontrada")


def sanitize_filename(name: str, extension: str = ".pdf") -> str:
    """Transforma o nome extraído em um nome de arquivo válido no Windows."""
    safe = unicodedata.normalize("NFKC", name)
    safe = INVALID_FILENAME_CHARS.sub("-", safe)
    safe = WHITESPACE.sub(" ", safe).strip(" .")

    if not safe:
        raise ValueError("o nome da empresa ficou vazio após a limpeza")

    max_stem_length = MAX_FILENAME_LENGTH - len(extension)
    safe = safe[:max_stem_length].rstrip(" .")
    if safe.upper() in WINDOWS_RESERVED_NAMES:
        safe = f"_{safe}"

    return f"{safe}{extension}"


def find_pdfs(folder: Path, recursive: bool = False) -> list[Path]:
    iterator: Iterable[Path] = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(
        (path for path in iterator if path.is_file() and path.suffix.lower() == ".pdf"),
        key=lambda path: str(path).casefold(),
    )


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.absolute()))


def _same_path(first: Path, second: Path) -> bool:
    return _path_key(first) == _path_key(second)


def _available_target(source: Path, filename: str, reserved: set[str]) -> Path:
    requested = source.with_name(filename)
    stem = requested.stem
    suffix = requested.suffix
    number = 1

    while True:
        if number == 1:
            candidate = requested
        else:
            extra = f" ({number})"
            allowed = MAX_FILENAME_LENGTH - len(suffix) - len(extra)
            candidate = source.with_name(f"{stem[:allowed].rstrip(' .')}{extra}{suffix}")

        key = _path_key(candidate)
        exists_as_another_file = candidate.exists() and not _same_path(candidate, source)
        if key not in reserved and not exists_as_another_file:
            reserved.add(key)
            return candidate
        number += 1


def analyze_folder(folder: Path, recursive: bool = False) -> list[RenamePlan]:
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        raise ValueError("selecione uma pasta válida")

    pdfs = find_pdfs(folder, recursive=recursive)
    reserved: set[str] = set()
    plans: list[RenamePlan] = []

    for pdf_path in pdfs:
        try:
            company = extract_company_name_from_pdf(pdf_path)
            filename = sanitize_filename(company)
            requested = pdf_path.with_name(filename)

            if _same_path(pdf_path, requested):
                reserved.add(_path_key(pdf_path))
                plans.append(
                    RenamePlan(
                        source=pdf_path,
                        target=pdf_path,
                        company=company,
                        status="already_named",
                        message="já está com o nome correto",
                    )
                )
                continue

            target = _available_target(pdf_path, filename, reserved)
            message = ""
            if target.name != filename:
                message = "foi adicionado um número para evitar duplicidade"
            plans.append(
                RenamePlan(
                    source=pdf_path,
                    target=target,
                    company=company,
                    status="ready",
                    message=message,
                )
            )
        except Exception as exc:
            plans.append(
                RenamePlan(
                    source=pdf_path,
                    target=None,
                    company=None,
                    status="error",
                    message=str(exc),
                )
            )

    return plans


def apply_renames(plans: Iterable[RenamePlan]) -> list[RenamePlan]:
    results: list[RenamePlan] = []

    for plan in plans:
        if plan.status != "ready" or plan.target is None:
            results.append(plan)
            continue

        try:
            if not plan.source.exists():
                raise FileNotFoundError("o arquivo original não existe mais")
            if plan.target.exists() and not _same_path(plan.source, plan.target):
                raise FileExistsError("o nome de destino passou a existir; analise novamente")

            plan.source.rename(plan.target)
            results.append(replace(plan, status="renamed", message="renomeado com sucesso"))
        except Exception as exc:
            results.append(replace(plan, status="error", message=str(exc)))

    return results


def summarize(plans: Iterable[RenamePlan]) -> dict[str, int]:
    counts = {
        "ready": 0,
        "renamed": 0,
        "already_named": 0,
        "error": 0,
    }
    for plan in plans:
        counts[plan.status] = counts.get(plan.status, 0) + 1
    return counts


def _display_path(path: Path, folder: Path) -> str:
    try:
        return str(path.relative_to(folder))
    except ValueError:
        return str(path)


def run_cli(folder: Path, recursive: bool, execute: bool) -> int:
    plans = analyze_folder(folder, recursive=recursive)

    if not plans:
        print("Nenhum PDF foi encontrado na pasta.")
        return 0

    for plan in plans:
        if plan.target:
            print(f"[{plan.status}] {plan.source.name} -> {plan.target.name}")
        else:
            print(f"[{plan.status}] {plan.source.name}: {plan.message}")

    if execute:
        plans = apply_renames(plans)
        print("\nRenomeação concluída.")
    else:
        print("\nEsta foi apenas uma simulação. Use --aplicar para renomear.")

    counts = summarize(plans)
    print(
        "Resumo: "
        f"{counts['renamed']} renomeado(s), "
        f"{counts['ready']} pronto(s), "
        f"{counts['already_named']} já correto(s), "
        f"{counts['error']} erro(s)."
    )
    return 1 if counts["error"] else 0


class RenamerApp:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.plans: list[RenamePlan] = []
        self.folder = Path.cwd()

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("1050x620")
        self.root.minsize(820, 480)

        self.folder_var = tk.StringVar(value="")
        self.recursive_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Selecione a pasta que contém os PDFs.")
        self._build_ui()

    def _build_ui(self) -> None:
        from tkinter import ttk

        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        ttk.Label(
            outer,
            text="Renomear PDFs pelo nome da empresa ou pessoa",
            font=("Segoe UI", 15, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        folder_row = ttk.Frame(outer)
        folder_row.grid(row=1, column=0, sticky="ew")
        folder_row.columnconfigure(0, weight=1)
        ttk.Entry(folder_row, textvariable=self.folder_var).grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Button(folder_row, text="Escolher pasta", command=self.choose_folder).grid(
            row=0, column=1
        )

        options = ttk.Frame(outer)
        options.grid(row=2, column=0, sticky="ew", pady=10)
        ttk.Checkbutton(
            options,
            text="Incluir PDFs das subpastas",
            variable=self.recursive_var,
        ).pack(side="left")
        self.analyze_button = ttk.Button(
            options, text="Analisar PDFs", command=self.start_analysis
        )
        self.analyze_button.pack(side="right")

        table_frame = ttk.Frame(outer)
        table_frame.grid(row=3, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table_frame,
            columns=("current", "new", "status"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("current", text="Arquivo atual")
        self.tree.heading("new", text="Novo nome")
        self.tree.heading("status", text="Situação")
        self.tree.column("current", width=380, minwidth=180)
        self.tree.column("new", width=380, minwidth=180)
        self.tree.column("status", width=180, minwidth=130)
        self.tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        bottom = ttk.Frame(outer)
        bottom.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(bottom, mode="indeterminate", length=130)
        self.progress.grid(row=0, column=1, padx=10)
        self.rename_button = ttk.Button(
            bottom,
            text="Renomear arquivos",
            command=self.rename_files,
            state="disabled",
        )
        self.rename_button.grid(row=0, column=2)

    def choose_folder(self) -> None:
        from tkinter import filedialog

        selected = filedialog.askdirectory(title="Escolha a pasta com os PDFs")
        if selected:
            self.folder_var.set(selected)
            self.start_analysis()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.analyze_button.configure(state=state)
        self.rename_button.configure(state="disabled" if busy else self.rename_button["state"])
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def start_analysis(self) -> None:
        from tkinter import messagebox

        raw_folder = self.folder_var.get().strip()
        if not raw_folder:
            messagebox.showinfo(APP_TITLE, "Primeiro, escolha uma pasta.")
            return

        folder = Path(raw_folder)
        if not folder.is_dir():
            messagebox.showerror(APP_TITLE, "A pasta informada não existe.")
            return

        self.folder = folder.resolve()
        self.status_var.set("Analisando os PDFs...")
        self._set_busy(True)
        self.rename_button.configure(state="disabled")

        worker = threading.Thread(
            target=self._analyze_worker,
            args=(self.folder, self.recursive_var.get()),
            daemon=True,
        )
        worker.start()

    def _analyze_worker(self, folder: Path, recursive: bool) -> None:
        try:
            plans = analyze_folder(folder, recursive=recursive)
            self.root.after(0, self._finish_analysis, plans, None)
        except Exception as exc:
            self.root.after(0, self._finish_analysis, [], str(exc))

    def _finish_analysis(self, plans: list[RenamePlan], error: str | None) -> None:
        from tkinter import messagebox

        self._set_busy(False)
        if error:
            self.status_var.set("A análise não pôde ser concluída.")
            messagebox.showerror(APP_TITLE, error)
            return

        self.plans = plans
        self._refresh_table()
        counts = summarize(plans)
        self.status_var.set(
            f"{len(plans)} PDF(s): {counts['ready']} para renomear, "
            f"{counts['already_named']} já correto(s), {counts['error']} com erro."
        )
        self.rename_button.configure(state="normal" if counts["ready"] else "disabled")

        if not plans:
            messagebox.showinfo(APP_TITLE, "Nenhum PDF foi encontrado nessa pasta.")

    def _refresh_table(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        status_labels = {
            "ready": "Pronto",
            "renamed": "Renomeado",
            "already_named": "Já está correto",
            "error": "Erro",
        }
        for plan in self.plans:
            current = _display_path(plan.source, self.folder)
            new_name = plan.target.name if plan.target else "-"
            status = status_labels.get(plan.status, plan.status)
            if plan.message:
                status = f"{status}: {plan.message}"
            self.tree.insert("", "end", values=(current, new_name, status))

    def rename_files(self) -> None:
        from tkinter import messagebox

        ready = summarize(self.plans)["ready"]
        if not ready:
            return
        confirmed = messagebox.askyesno(
            APP_TITLE,
            f"Renomear {ready} arquivo(s) conforme a prévia?\n\n"
            "Nenhum arquivo existente será sobrescrito.",
        )
        if not confirmed:
            return

        self.plans = apply_renames(self.plans)
        self._refresh_table()
        counts = summarize(self.plans)
        self.rename_button.configure(state="disabled")
        self.status_var.set(
            f"Concluído: {counts['renamed']} renomeado(s), "
            f"{counts['already_named']} já correto(s), {counts['error']} erro(s)."
        )
        if counts["error"]:
            messagebox.showwarning(
                APP_TITLE,
                "A renomeação terminou, mas alguns arquivos tiveram erro. "
                "Veja os detalhes na coluna Situação.",
            )
        else:
            messagebox.showinfo(APP_TITLE, "Arquivos renomeados com sucesso.")

    def run(self) -> None:
        self.root.mainloop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Renomeia relatórios fiscais em PDF usando o nome da empresa."
    )
    parser.add_argument(
        "pasta",
        nargs="?",
        type=Path,
        help="pasta com os PDFs; sem este argumento, abre a interface gráfica",
    )
    parser.add_argument(
        "--recursivo",
        action="store_true",
        help="inclui PDFs dentro de subpastas",
    )
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="executa a renomeação; sem esta opção, apenas mostra uma prévia",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.pasta:
        try:
            return run_cli(args.pasta, recursive=args.recursivo, execute=args.aplicar)
        except Exception as exc:
            print(f"Erro: {exc}", file=sys.stderr)
            return 1

    try:
        RenamerApp().run()
        return 0
    except Exception as exc:
        print(f"Não foi possível abrir o programa: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
