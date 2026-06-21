#!/usr/bin/env python3
"""
media_datetime_shift.py

Ferramenta interativa para corrigir data/hora de arquivos de mídia
(fotos e vídeos) que foram registrados com o fuso horário errado.

Ajusta:
  - Metadados EXIF/QuickTime (DateTimeOriginal, CreateDate, ModifyDate
    e tags equivalentes de vídeo), via exiftool.
  - Datas do sistema de arquivos no macOS (modificação e, quando
    possível, criação/"Date Added" do Finder).

Formatos suportados: JPEG/JPG, HEIC/HEIF, DNG, RAW (CR2, CR3, NEF, ARW,
ORF, RW2, RAF), TIFF, PNG, e vídeos MOV/MP4/M4V/AVI/3GP/MTS/M2TS.

Pré-requisitos:
  - exiftool instalado e disponível no PATH (brew install exiftool)
  - (opcional) Xcode Command Line Tools, para ajustar a data de criação
    no macOS via 'SetFile' (xcode-select --install)

Uso:
    python3 media_datetime_shift.py
"""

import glob
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


# ---------------------------------------------------------------------------
# Configuração de formatos suportados
# ---------------------------------------------------------------------------

PHOTO_EXTENSIONS = {
    ".jpg", ".jpeg", ".heic", ".heif", ".dng",
    ".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".raf", ".raw",
    ".tif", ".tiff", ".png",
}

VIDEO_EXTENSIONS = {
    ".mov", ".mp4", ".m4v", ".avi", ".3gp", ".mts", ".m2ts",
}

SUPPORTED_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS

# Tags de vídeo (QuickTime/MP4) que -AllDates não cobre garantidamente
VIDEO_DATE_TAGS = (
    "QuickTime:CreateDate",
    "QuickTime:ModifyDate",
    "QuickTime:TrackCreateDate",
    "QuickTime:TrackModifyDate",
    "QuickTime:MediaCreateDate",
    "QuickTime:MediaModifyDate",
)


# ---------------------------------------------------------------------------
# Funções "puras" (fáceis de testar) — parsing e descoberta de arquivos
# ---------------------------------------------------------------------------

def parse_signed_int_offset(raw: str) -> int:
    """Converte uma string como '+3', '-5' ou '27' em um inteiro com sinal.

    Usada tanto para o ajuste de dias quanto de horas — é puramente um
    parser de número com sinal, sem conhecimento da unidade.

    Levanta ValueError se o formato for inválido ou o valor for zero.
    """
    raw = raw.strip()
    if not raw:
        raise ValueError("valor vazio")

    sign = 1
    body = raw
    if raw[0] in "+-":
        sign = -1 if raw[0] == "-" else 1
        body = raw[1:]

    if not body.isdigit():
        raise ValueError(f"formato inválido: {raw!r}")

    value = sign * int(body)
    if value == 0:
        raise ValueError("o ajuste não pode ser zero")
    return value


def build_exiftool_shift_expr(hours: int) -> str:
    """Monta a expressão de shift no formato esperado pelo exiftool.

    Formato: '[+-]=Y:M:D H:M:S'. Mantemos a parte Y:M:D zerada e
    colocamos o valor de horas (que pode ser >24, o exiftool resolve
    o "carry" para dias/meses/anos automaticamente) na parte H:M:S.
    """
    sign = "+" if hours >= 0 else "-"
    return f"{sign}=0:0:0 {abs(hours)}:0:0"


def parse_exiftool_datetime(value: str):
    """Converte uma string de data no formato do exiftool
    ('YYYY:MM:DD HH:MM:SS') em datetime. Retorna None se vazia,
    ausente, ou em formato inesperado (ex: '0000:00:00 00:00:00',
    comum em arquivos sem data gravada).
    """
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def discover_files_in_directory(directory: str):
    """Busca recursiva por arquivos de mídia suportados em um diretório."""
    found = []
    for root, _dirs, filenames in os.walk(directory):
        for fname in filenames:
            ext = Path(fname).suffix.lower()
            if ext in SUPPORTED_EXTENSIONS:
                found.append(os.path.join(root, fname))
    return sorted(found)


def resolve_specific_files(raw_input: str):
    """Resolve uma lista de caminhos/curingas digitados pelo usuário.

    Retorna (arquivos_validos, avisos).
    """
    files = []
    warnings = []
    parts = [p.strip() for p in raw_input.split(",") if p.strip()]

    for part in parts:
        expanded = os.path.expanduser(part)
        matches = glob.glob(expanded)
        if not matches and os.path.isfile(expanded):
            matches = [expanded]
        if not matches:
            warnings.append(f"Nenhum arquivo encontrado para: {part}")
            continue
        for m in matches:
            ext = Path(m).suffix.lower()
            if ext in SUPPORTED_EXTENSIONS:
                files.append(m)
            else:
                warnings.append(f"Extensão não suportada, ignorada: {m}")

    return sorted(set(files)), warnings


def summarize_extensions(files):
    """Retorna um Counter com a contagem de arquivos por extensão."""
    return Counter(Path(f).suffix.upper().lstrip(".") for f in files)


# ---------------------------------------------------------------------------
# Integração com exiftool e sistema de arquivos
# ---------------------------------------------------------------------------

def check_exiftool():
    if shutil.which("exiftool") is None:
        print("[ERRO] 'exiftool' não encontrado no PATH.")
        print("Instale com: brew install exiftool")
        sys.exit(1)
    result = subprocess.run(["exiftool", "-ver"], capture_output=True, text=True)
    print(f"✓ exiftool encontrado (versão {result.stdout.strip()})")


def check_setfile() -> bool:
    return shutil.which("SetFile") is not None


def read_primary_datetime(file_path: str):
    """Lê a data/hora ORIGINAL gravada no arquivo (antes do shift),
    usada como única fonte da verdade para corrigir tanto o EXIF
    quanto o sistema de arquivos a partir do mesmo valor.

    Tenta 'DateTimeOriginal' primeiro (fotos), depois 'CreateDate'
    como alternativa (comum em vídeos e alguns formatos sem
    DateTimeOriginal). Retorna um datetime ou None se nenhuma tag de
    data válida for encontrada.
    """
    for tag in ("-DateTimeOriginal", "-CreateDate"):
        result = subprocess.run(
            ["exiftool", "-s3", tag, file_path],
            capture_output=True, text=True,
        )
        dt = parse_exiftool_datetime(result.stdout)
        if dt is not None:
            return dt
    return None


def shift_exif_metadata(file_path: str, hours: int, keep_backup: bool):
    """Desloca as tags de data/hora EXIF/QuickTime de um arquivo.

    Retorna (sucesso: bool, mensagem: str).
    """
    shift_expr = build_exiftool_shift_expr(hours)

    cmd = ["exiftool", "-m", f"-AllDates{shift_expr}"]
    if not keep_backup:
        cmd.append("-overwrite_original")

    if Path(file_path).suffix.lower() in VIDEO_EXTENSIONS:
        for tag in VIDEO_DATE_TAGS:
            cmd.append(f"-{tag}{shift_expr}")

    cmd.append(file_path)
    result = subprocess.run(cmd, capture_output=True, text=True)
    ok = result.returncode == 0 and "error" not in result.stdout.lower()
    return ok, (result.stdout + result.stderr).strip()


def sync_filesystem_dates_to(file_path: str, target_dt: datetime, has_setfile: bool):
    """Define mtime/atime (e birthtime, se possível) do arquivo para
    coincidir EXATAMENTE com `target_dt` — a data/hora já corrigida,
    lida do EXIF antes do shift e somada ao deslocamento.

    Isso evita a divergência entre EXIF e Finder que ocorre quando o
    mtime em disco não refletia a data real da foto/vídeo (comum após
    copiar, sincronizar com a nuvem, ou fazer AirDrop do arquivo).
    """
    ts = target_dt.timestamp()
    os.utime(file_path, (ts, ts))

    if not has_setfile:
        return

    formatted = target_dt.strftime("%m/%d/%Y %H:%M:%S")
    subprocess.run(["SetFile", "-d", formatted, file_path], capture_output=True, text=True)


def shift_filesystem_dates_relative(file_path: str, hours: int, has_setfile: bool):
    """Fallback: desloca mtime/atime/birthtime relativamente ao que já
    estava no disco. Só é usado quando o arquivo não tem nenhuma tag
    de data EXIF/QuickTime legível (sync_filesystem_dates_to não pode
    ser usada nesse caso, pois não há data de referência confiável).
    """
    stat = os.stat(file_path)
    delta = timedelta(hours=hours)

    new_mtime = datetime.fromtimestamp(stat.st_mtime) + delta
    new_atime = datetime.fromtimestamp(stat.st_atime) + delta
    os.utime(file_path, (new_atime.timestamp(), new_mtime.timestamp()))

    if not has_setfile:
        return

    birth_ts = getattr(stat, "st_birthtime", None)
    if birth_ts is None:
        return  # não é macOS / não suportado

    new_birth = datetime.fromtimestamp(birth_ts) + delta
    formatted = new_birth.strftime("%m/%d/%Y %H:%M:%S")
    subprocess.run(["SetFile", "-d", formatted, file_path], capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Fluxo interativo
# ---------------------------------------------------------------------------

MENU_BANNER = "=" * 45

# (rótulo, pergunta com concordância correta, exemplo curto,
#  multiplicador para converter em horas totais)
MENU_OPTIONS = {
    "1": {
        "titulo": "Alterar DATA",
        "unidade": "dias",
        "pergunta": "Quantos dias",
        "exemplos": "+1, -1",
        "multiplicador": 24,
    },
    "2": {
        "titulo": "Alterar HORA",
        "unidade": "horas",
        "pergunta": "Quantas horas",
        "exemplos": "+1, -1",
        "multiplicador": 1,
    },
}


def print_header(subtitle: str = ""):
    print(f"\n{MENU_BANNER}")
    print("  Media DateTime Shift")
    if subtitle:
        print(f"  {subtitle}")
    print(MENU_BANNER)


def print_main_menu():
    print_header("Corrige data/hora de fotos e vídeos")
    print("\nO que deseja fazer?\n")
    print("  1 - Alterar DATA  (ajusta por dias, ex: +1, -3)")
    print("  2 - Alterar HORA  (ajusta por horas, ex: +3, -5)")
    print("  0 - Sair")


def ask_offset(option: dict) -> int:
    """Pergunta o valor de ajuste (dias ou horas, conforme a opção)
    e retorna já convertido para o total de HORAS, unidade usada
    internamente pelo exiftool e pelo ajuste do sistema de arquivos.
    """
    while True:
        raw = input(f"\n{option['pergunta']} ({option['exemplos']})? ")
        try:
            value = parse_signed_int_offset(raw)
            return value, value * option["multiplicador"]
        except ValueError as exc:
            print(f"  Entrada inválida ({exc}). Tente novamente.")


def ask_target_files():
    print("\nO que deseja processar?")
    print("  [1] Diretório inteiro (busca recursiva)")
    print("  [2] Arquivos específicos")
    choice = input("Escolha [1/2]: ").strip()

    if choice == "1":
        directory = os.path.expanduser(input("Caminho do diretório: ").strip())
        if not os.path.isdir(directory):
            print(f"  Diretório não encontrado: {directory}")
            return None
        return discover_files_in_directory(directory)

    if choice == "2":
        raw = input("Caminho completo (pode separar por vírgula): ")
        files, warnings = resolve_specific_files(raw)
        for w in warnings:
            print(f"  Aviso: {w}")
        return files

    print("Opção inválida.")
    return None


def print_summary(files):
    counts = summarize_extensions(files)
    print(f"\nEncontrados {len(files)} arquivo(s):")
    for ext, n in sorted(counts.items()):
        print(f"  - {n} {ext}")


def confirm(prompt: str, default_yes: bool = False) -> bool:
    suffix = "[S/n]" if default_yes else "[s/N]"
    raw = input(f"{prompt} {suffix}: ").strip().lower()
    if not raw:
        return default_yes
    return raw == "s"


def format_shift_line(file_path: str, original_dt, new_dt) -> str:
    """Monta a linha de log mostrando claramente o antes/depois de um
    arquivo. Função pura, fácil de testar sem subprocess/exiftool.
    """
    if original_dt is None:
        return f"{file_path}  (sem data EXIF; sistema de arquivos deslocado pelo mtime anterior)"
    fmt = "%Y-%m-%d %H:%M:%S"
    return f"{file_path}  ({original_dt.strftime(fmt)} -> {new_dt.strftime(fmt)})"


def log_line(prefix: str, msg: str):
    """Imprime uma linha sem quebrar a barra de progresso do tqdm,
    quando ela estiver ativa."""
    line = f"{prefix} {msg}"
    if HAS_TQDM:
        tqdm.write(line)
    else:
        print(line)


def process_files(files, total_hours, dry_run, keep_backup, has_setfile):
    success, errors, no_exif_date = 0, [], []
    iterator = tqdm(files, unit="arquivo") if HAS_TQDM else files
    delta = timedelta(hours=total_hours)

    for f in iterator:
        # Lê a data ORIGINAL antes de alterar nada — é a referência
        # usada tanto para mostrar o antes/depois quanto para
        # sincronizar o sistema de arquivos, independente do mtime
        # que já estava em disco.
        original_dt = read_primary_datetime(f)
        new_dt = original_dt + delta if original_dt is not None else None

        if dry_run:
            log_line("[SIMULAÇÃO]", format_shift_line(f, original_dt, new_dt))
            success += 1
            continue

        ok, msg = shift_exif_metadata(f, total_hours, keep_backup)
        if not ok:
            errors.append((f, msg))
            log_line("✗", f"{f}: {msg}")
            continue

        if original_dt is not None:
            sync_filesystem_dates_to(f, new_dt, has_setfile)
        else:
            # Sem nenhuma tag de data legível: não há referência
            # confiável, então só deslocamos o que já estava no disco.
            shift_filesystem_dates_relative(f, total_hours, has_setfile)
            no_exif_date.append(f)

        success += 1
        log_line("✓", format_shift_line(f, original_dt, new_dt))

    print(f"\nConcluído: {success} sucesso(s), {len(errors)} erro(s).")
    if no_exif_date:
        print(
            f"\nAviso: {len(no_exif_date)} arquivo(s) sem data EXIF/QuickTime "
            "legível — o sistema de arquivos foi deslocado a partir do mtime "
            "que já estava em disco (pode não ser exato):"
        )
        for f in no_exif_date:
            print(f"  - {f}")
    if errors:
        print("\nDetalhes dos erros:")
        for f, msg in errors:
            print(f"  - {f}: {msg}")


def run_shift_flow(option_key: str, has_setfile: bool):
    """Executa o fluxo completo (perguntar ajuste -> escolher arquivos ->
    confirmar -> processar) para a opção de menu escolhida (data ou hora).
    """
    option = MENU_OPTIONS[option_key]
    print_header(option["titulo"])

    value, total_hours = ask_offset(option)
    files = ask_target_files()

    if not files:
        print("\nNenhum arquivo de mídia suportado foi encontrado.")
        return

    print_summary(files)

    dry_run = confirm("\nExecutar em modo simulação (não altera nada)?", default_yes=False)
    keep_backup = confirm("Manter backups dos arquivos originais (recomendado)?", default_yes=True)

    print("\nResumo da operação:")
    print(f"  Ajuste: {value:+d} {option['unidade']} (total: {total_hours:+d} horas)")
    print(f"  Arquivos: {len(files)}")
    print(f"  Modo: {'SIMULAÇÃO (nada será alterado)' if dry_run else 'APLICAR ALTERAÇÕES'}")
    print(f"  Backups: {'sim' if keep_backup else 'NÃO (sobrescreve o original)'}")

    if not confirm("\nConfirma a operação?", default_yes=False):
        print("Operação cancelada.")
        return

    process_files(files, total_hours, dry_run, keep_backup, has_setfile)


def startup_checks() -> bool:
    """Confere exiftool (obrigatório) e SetFile (opcional). Retorna
    has_setfile; encerra o programa se exiftool não estiver disponível.
    """
    check_exiftool()
    has_setfile = check_setfile()
    if not has_setfile:
        print(
            "\n[Aviso] 'SetFile' não encontrado — a data de CRIAÇÃO no "
            "Finder não será alterada (apenas a de modificação).\n"
            "Para habilitar, instale as Xcode Command Line Tools:\n"
            "  xcode-select --install"
        )
    return has_setfile


def run():
    has_setfile = startup_checks()

    while True:
        print_main_menu()
        choice = input("\nEscolha uma opção: ").strip()

        if choice == "0":
            print("\nAté mais!")
            break
        elif choice in MENU_OPTIONS:
            run_shift_flow(choice, has_setfile)
            input("\nPressione ENTER para voltar ao menu...")
        else:
            print("\nOpção inválida. Escolha 1, 2 ou 0.")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\nOperação interrompida pelo usuário.")
        sys.exit(1)
