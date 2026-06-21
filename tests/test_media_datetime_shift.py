"""Testes unitários para as funções de parsing e descoberta de arquivos.

Executar com:
    source venv/bin/activate
    pip install -r requirements-dev.txt
    pytest
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime
from unittest.mock import patch

import pytest
from media_datetime_shift import (
    MENU_OPTIONS,
    build_exiftool_shift_expr,
    format_shift_line,
    parse_exiftool_datetime,
    parse_signed_int_offset,
    process_files,
    resolve_specific_files,
    summarize_extensions,
)


class TestParseSignedIntOffset:
    def test_positive_with_plus(self):
        assert parse_signed_int_offset("+3") == 3

    def test_negative_with_minus(self):
        assert parse_signed_int_offset("-5") == -5

    def test_no_sign_defaults_positive(self):
        assert parse_signed_int_offset("7") == 7

    def test_large_value_crossing_midnight(self):
        assert parse_signed_int_offset("+27") == 27

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            parse_signed_int_offset("0")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_signed_int_offset("")

    def test_garbage_raises(self):
        with pytest.raises(ValueError):
            parse_signed_int_offset("abc")


class TestParseExiftoolDatetime:
    def test_valid_datetime(self):
        assert parse_exiftool_datetime("2026:06:21 11:45:00") == datetime(2026, 6, 21, 11, 45, 0)

    def test_empty_string_returns_none(self):
        assert parse_exiftool_datetime("") is None

    def test_none_returns_none(self):
        assert parse_exiftool_datetime(None) is None

    def test_zeroed_date_returns_none(self):
        # Comum em arquivos sem data gravada de verdade.
        assert parse_exiftool_datetime("0000:00:00 00:00:00") is None

    def test_garbage_returns_none(self):
        assert parse_exiftool_datetime("não é uma data") is None

    def test_strips_whitespace(self):
        assert parse_exiftool_datetime("  2026:06:21 11:45:00  ") == datetime(2026, 6, 21, 11, 45, 0)


class TestFormatShiftLine:
    def test_shows_before_and_after(self):
        line = format_shift_line(
            "/tmp/foto.jpg",
            datetime(2026, 6, 21, 11, 45, 0),
            datetime(2026, 6, 21, 12, 45, 0),
        )
        assert "2026-06-21 11:45:00" in line
        assert "2026-06-21 12:45:00" in line
        assert "/tmp/foto.jpg" in line

    def test_no_exif_date_shows_warning_text(self):
        line = format_shift_line("/tmp/sem_data.jpg", None, None)
        assert "sem data EXIF" in line


class TestProcessFilesDryRunDoesNotWrite:
    """Modo simulação deve ler a data (para mostrar o preview), mas
    NUNCA chamar as funções que de fato escrevem no arquivo."""

    def test_dry_run_never_writes(self, tmp_path):
        jpg = tmp_path / "foto.jpg"
        jpg.write_bytes(b"\xff\xd8\xff")

        with patch(
            "media_datetime_shift.read_primary_datetime",
            return_value=datetime(2026, 6, 21, 11, 45, 0),
        ), patch(
            "media_datetime_shift.shift_exif_metadata"
        ) as mock_shift_exif, patch(
            "media_datetime_shift.sync_filesystem_dates_to"
        ) as mock_sync, patch(
            "media_datetime_shift.shift_filesystem_dates_relative"
        ) as mock_relative:
            process_files([str(jpg)], total_hours=1, dry_run=True, keep_backup=True, has_setfile=False)

        mock_shift_exif.assert_not_called()
        mock_sync.assert_not_called()
        mock_relative.assert_not_called()


class TestProcessFilesUsesExifDateNotStaleMtime:
    """Cobre o bug relatado: o sistema de arquivos deve seguir a data
    GRAVADA NO ARQUIVO (EXIF), e não o mtime que já estava em disco
    (que pode ter sido alterado ao copiar/sincronizar o arquivo)."""

    def test_filesystem_synced_to_exif_date_plus_delta(self, tmp_path):
        jpg = tmp_path / "foto.jpg"
        jpg.write_bytes(b"\xff\xd8\xff")

        # Simula um mtime em disco BEM diferente da data real da foto
        # (ex: arquivo foi copiado "agora" para a pasta de teste).
        stale_timestamp = datetime(2099, 1, 1, 0, 0, 0).timestamp()
        os.utime(jpg, (stale_timestamp, stale_timestamp))

        # A data "real" gravada na foto é 11:45; +1 hora deve virar 12:45.
        original_dt = datetime(2026, 6, 21, 11, 45, 0)

        with patch(
            "media_datetime_shift.read_primary_datetime", return_value=original_dt
        ), patch(
            "media_datetime_shift.shift_exif_metadata", return_value=(True, "")
        ), patch(
            "media_datetime_shift.sync_filesystem_dates_to"
        ) as mock_sync, patch(
            "media_datetime_shift.shift_filesystem_dates_relative"
        ) as mock_relative:
            process_files([str(jpg)], total_hours=1, dry_run=False, keep_backup=True, has_setfile=False)

        # sync_filesystem_dates_to deve ter sido chamada com 12:45,
        # derivada da data EXIF original — não com o mtime obsoleto.
        mock_sync.assert_called_once_with(str(jpg), datetime(2026, 6, 21, 12, 45, 0), False)
        mock_relative.assert_not_called()

    def test_falls_back_to_relative_shift_when_no_exif_date(self, tmp_path):
        jpg = tmp_path / "sem_data.jpg"
        jpg.write_bytes(b"\xff\xd8\xff")

        with patch(
            "media_datetime_shift.read_primary_datetime", return_value=None
        ), patch(
            "media_datetime_shift.shift_exif_metadata", return_value=(True, "")
        ), patch(
            "media_datetime_shift.sync_filesystem_dates_to"
        ) as mock_sync, patch(
            "media_datetime_shift.shift_filesystem_dates_relative"
        ) as mock_relative:
            process_files([str(jpg)], total_hours=1, dry_run=False, keep_backup=True, has_setfile=False)

        mock_relative.assert_called_once_with(str(jpg), 1, False)
        mock_sync.assert_not_called()

    def test_skips_filesystem_sync_when_exif_write_fails(self, tmp_path):
        jpg = tmp_path / "falha.jpg"
        jpg.write_bytes(b"\xff\xd8\xff")

        with patch(
            "media_datetime_shift.read_primary_datetime",
            return_value=datetime(2026, 6, 21, 11, 45, 0),
        ), patch(
            "media_datetime_shift.shift_exif_metadata", return_value=(False, "erro simulado")
        ), patch(
            "media_datetime_shift.sync_filesystem_dates_to"
        ) as mock_sync, patch(
            "media_datetime_shift.shift_filesystem_dates_relative"
        ) as mock_relative:
            process_files([str(jpg)], total_hours=1, dry_run=False, keep_backup=True, has_setfile=False)

        mock_sync.assert_not_called()
        mock_relative.assert_not_called()


class TestMenuOptions:
    """Garante que o menu (1=data, 2=hora) converte corretamente para
    o total de horas usado internamente pelo motor de shift."""

    def test_date_option_multiplies_by_24(self):
        option = MENU_OPTIONS["1"]
        days = parse_signed_int_offset("+2")
        assert days * option["multiplicador"] == 48

    def test_hour_option_uses_value_directly(self):
        option = MENU_OPTIONS["2"]
        hours = parse_signed_int_offset("-5")
        assert hours * option["multiplicador"] == -5

    def test_exit_option_not_in_menu(self):
        assert "0" not in MENU_OPTIONS


class TestBuildExiftoolShiftExpr:
    def test_positive_shift(self):
        assert build_exiftool_shift_expr(3) == "+=0:0:0 3:0:0"

    def test_negative_shift(self):
        assert build_exiftool_shift_expr(-5) == "-=0:0:0 5:0:0"

    def test_shift_above_24_hours(self):
        # O exiftool resolve o carry de dias internamente.
        assert build_exiftool_shift_expr(27) == "+=0:0:0 27:0:0"


class TestResolveSpecificFiles:
    def test_unsupported_extension_warns(self, tmp_path):
        txt_file = tmp_path / "nota.txt"
        txt_file.write_text("não é mídia")
        files, warnings = resolve_specific_files(str(txt_file))
        assert files == []
        assert any("não suportada" in w for w in warnings)

    def test_supported_extension_found(self, tmp_path):
        jpg_file = tmp_path / "foto.jpg"
        jpg_file.write_bytes(b"\xff\xd8\xff")
        files, warnings = resolve_specific_files(str(jpg_file))
        assert files == [str(jpg_file)]
        assert warnings == []

    def test_missing_file_warns(self, tmp_path):
        missing = tmp_path / "nao_existe.jpg"
        files, warnings = resolve_specific_files(str(missing))
        assert files == []
        assert any("Nenhum arquivo encontrado" in w for w in warnings)

    def test_glob_pattern(self, tmp_path):
        (tmp_path / "a.jpg").write_bytes(b"x")
        (tmp_path / "b.jpg").write_bytes(b"x")
        (tmp_path / "c.txt").write_bytes(b"x")
        files, _ = resolve_specific_files(str(tmp_path / "*.jpg"))
        assert len(files) == 2


class TestSummarizeExtensions:
    def test_counts_by_extension(self):
        files = ["a.JPG", "b.jpg", "c.heic", "d.JPG"]
        counts = summarize_extensions(files)
        assert counts["JPG"] == 3
        assert counts["HEIC"] == 1
