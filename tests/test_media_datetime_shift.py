"""Testes unitários para as funções de parsing e descoberta de arquivos.

Executar com:
    source venv/bin/activate
    pip install -r requirements-dev.txt
    pytest
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from media_datetime_shift import (
    MENU_OPTIONS,
    backup_file_path,
    build_exiftool_shift_expr,
    flush_pending_writes,
    format_shift_line,
    format_timedelta,
    parse_exiftool_datetime,
    parse_signed_int_offset,
    parse_target_datetime,
    process_files,
    resolve_specific_files,
    run_set_exact_datetime_flow,
    shift_exif_metadata,
    shift_filesystem_dates_relative,
    summarize_extensions,
    sync_filesystem_dates_to,
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
            process_files([str(jpg)], timedelta(hours=1), dry_run=True, keep_backup=True, has_setfile=False)

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
            process_files([str(jpg)], timedelta(hours=1), dry_run=False, keep_backup=True, has_setfile=False)

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
            process_files([str(jpg)], timedelta(hours=1), dry_run=False, keep_backup=True, has_setfile=False)

        mock_relative.assert_called_once_with(str(jpg), timedelta(hours=1), False)
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
            process_files([str(jpg)], timedelta(hours=1), dry_run=False, keep_backup=True, has_setfile=False)

        mock_sync.assert_not_called()
        mock_relative.assert_not_called()


class TestBackupFilePath:
    def test_appends_original_suffix(self):
        assert backup_file_path("/tmp/foto.jpg") == "/tmp/foto.jpg_original"


class TestShiftExifMetadataBackupHandling:
    """O backup agora é feito por NÓS (não pelo exiftool), sempre
    sobrescrevendo o anterior. Isso corrige o comportamento confuso do
    exiftool, que só cria o backup na primeira vez e não o atualiza
    nas execuções seguintes — fazendo o backup "ficar para trás" depois
    de múltiplos testes no mesmo arquivo."""

    @staticmethod
    def _mock_subprocess_run():
        patcher = patch("media_datetime_shift.subprocess.run")
        mock_run = patcher.start()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "1 image files updated"
        mock_run.return_value.stderr = ""
        return patcher, mock_run

    def test_creates_backup_with_current_content_when_keep_backup_true(self, tmp_path):
        f = tmp_path / "foto.jpg"
        f.write_bytes(b"conteudo v1")

        patcher, _ = self._mock_subprocess_run()
        try:
            shift_exif_metadata(str(f), timedelta(hours=1), keep_backup=True)
        finally:
            patcher.stop()

        backup = tmp_path / "foto.jpg_original"
        assert backup.exists()
        assert backup.read_bytes() == b"conteudo v1"

    def test_backup_is_overwritten_each_run_not_frozen_on_first(self, tmp_path):
        f = tmp_path / "foto.jpg"
        f.write_bytes(b"estado 1")

        patcher, _ = self._mock_subprocess_run()
        try:
            shift_exif_metadata(str(f), timedelta(hours=1), keep_backup=True)
        finally:
            patcher.stop()
        assert (tmp_path / "foto.jpg_original").read_bytes() == b"estado 1"

        # Simula o exiftool tendo alterado o arquivo principal na 1a execução.
        f.write_bytes(b"estado 2 (resultado da 1a execucao)")

        patcher, _ = self._mock_subprocess_run()
        try:
            shift_exif_metadata(str(f), timedelta(hours=1), keep_backup=True)
        finally:
            patcher.stop()

        # O backup deve refletir o estado imediatamente ANTERIOR a esta
        # execução (estado 2), não mais travado no estado 1.
        assert (tmp_path / "foto.jpg_original").read_bytes() == b"estado 2 (resultado da 1a execucao)"

    def test_no_backup_created_when_keep_backup_false(self, tmp_path):
        f = tmp_path / "foto.jpg"
        f.write_bytes(b"conteudo")

        patcher, _ = self._mock_subprocess_run()
        try:
            shift_exif_metadata(str(f), timedelta(hours=1), keep_backup=False)
        finally:
            patcher.stop()

        assert not (tmp_path / "foto.jpg_original").exists()

    def test_always_passes_overwrite_original_to_exiftool(self, tmp_path):
        # Como o backup agora é feito por nós, sempre usamos
        # -overwrite_original no exiftool, independente de keep_backup,
        # para não depender do mecanismo de backup dele.
        f = tmp_path / "foto.jpg"
        f.write_bytes(b"conteudo")

        patcher, mock_run = self._mock_subprocess_run()
        try:
            shift_exif_metadata(str(f), timedelta(hours=1), keep_backup=True)
            cmd_with_backup = mock_run.call_args[0][0]
        finally:
            patcher.stop()

        patcher, mock_run = self._mock_subprocess_run()
        try:
            shift_exif_metadata(str(f), timedelta(hours=1), keep_backup=False)
            cmd_without_backup = mock_run.call_args[0][0]
        finally:
            patcher.stop()

        assert "-overwrite_original" in cmd_with_backup
        assert "-overwrite_original" in cmd_without_backup

    def test_backup_failure_prevents_exif_write(self, tmp_path):
        f = tmp_path / "foto.jpg"
        f.write_bytes(b"conteudo")

        with patch(
            "media_datetime_shift.shutil.copy2", side_effect=OSError("disco cheio")
        ), patch("media_datetime_shift.subprocess.run") as mock_run:
            ok, msg = shift_exif_metadata(str(f), timedelta(hours=1), keep_backup=True)

        assert ok is False
        assert "backup" in msg.lower()
        mock_run.assert_not_called()


class TestFlushPendingWrites:
    """Cobre o fix da condição de corrida observada em mídia removível
    lenta (cartão SD via leitor USB): uma escrita grande do exiftool
    podia ainda estar em buffer quando ajustávamos o mtime logo
    depois, e ao ser fisicamente concluída minutos/segundos depois,
    sobrescrevia silenciosamente nosso ajuste de data."""

    def test_does_not_raise_on_real_file(self, tmp_path):
        f = tmp_path / "video.mp4"
        f.write_bytes(b"conteudo de teste")
        flush_pending_writes(str(f))  # não deve levantar exceção

    def test_does_not_raise_on_missing_file(self):
        # Mídia/SO sem suporte, ou caminho inválido: não deve quebrar
        # o fluxo principal, só seguimos sem o flush.
        flush_pending_writes("/caminho/que/nao/existe.mp4")


class TestSyncFilesystemDatesFlushOrdering:
    """O flush precisa acontecer ANTES do os.utime() — é a ordem que
    garante que nosso ajuste de data seja a última coisa a tocar no
    arquivo, vencendo qualquer escrita atrasada do exiftool."""

    def test_sync_flushes_before_utime(self, tmp_path):
        f = tmp_path / "video.mp4"
        f.write_bytes(b"conteudo")
        call_order = []

        with patch(
            "media_datetime_shift.flush_pending_writes",
            side_effect=lambda p: call_order.append("flush"),
        ), patch(
            "media_datetime_shift.os.utime",
            side_effect=lambda *a, **k: call_order.append("utime"),
        ):
            sync_filesystem_dates_to(str(f), datetime(2026, 6, 17, 13, 18, 21), has_setfile=False)

        assert call_order == ["flush", "utime"]

    def test_relative_shift_flushes_before_utime(self, tmp_path):
        f = tmp_path / "video.mp4"
        f.write_bytes(b"conteudo")
        call_order = []

        with patch(
            "media_datetime_shift.flush_pending_writes",
            side_effect=lambda p: call_order.append("flush"),
        ), patch(
            "media_datetime_shift.os.utime",
            side_effect=lambda *a, **k: call_order.append("utime"),
        ):
            shift_filesystem_dates_relative(str(f), timedelta(hours=1), has_setfile=False)

        assert call_order == ["flush", "utime"]

    def test_sync_still_sets_correct_timestamp_after_flush(self, tmp_path):
        # Garante que o flush não interfere no valor final aplicado.
        f = tmp_path / "video.mp4"
        f.write_bytes(b"conteudo")
        target = datetime(2026, 6, 17, 13, 18, 21)

        sync_filesystem_dates_to(str(f), target, has_setfile=False)

        result = datetime.fromtimestamp(os.stat(str(f)).st_mtime)
        assert result == target


class TestMenuOptions:
    """Garante que o menu (1=data, 2=hora) converte corretamente para
    o timedelta usado internamente pelo motor de shift."""

    def test_date_option_produces_days_as_timedelta(self):
        option = MENU_OPTIONS["1"]
        value = parse_signed_int_offset("+2")
        delta = timedelta(hours=value * option["multiplicador"])
        assert delta == timedelta(days=2)

    def test_hour_option_produces_hours_as_timedelta(self):
        option = MENU_OPTIONS["2"]
        value = parse_signed_int_offset("-5")
        delta = timedelta(hours=value * option["multiplicador"])
        assert delta == timedelta(hours=-5)

    def test_exit_option_not_in_menu(self):
        assert "0" not in MENU_OPTIONS

    def test_set_exact_datetime_option_not_in_menu_options(self):
        # A opção 3 ("Definir data/hora exata") tem fluxo próprio
        # (run_set_exact_datetime_flow), não usa o padrão
        # unidade/multiplicador de MENU_OPTIONS.
        assert "3" not in MENU_OPTIONS


class TestBuildExiftoolShiftExpr:
    def test_positive_hours_only(self):
        assert build_exiftool_shift_expr(timedelta(hours=3)) == "+=0:0:0 3:0:0"

    def test_negative_hours_only(self):
        assert build_exiftool_shift_expr(timedelta(hours=-5)) == "-=0:0:0 5:0:0"

    def test_hours_above_24_resolved_as_days_by_timedelta(self):
        # timedelta já normaliza 27h em 1 dia + 3h internamente.
        assert build_exiftool_shift_expr(timedelta(hours=27)) == "+=0:0:1 3:0:0"

    def test_sub_hour_precision_minutes_and_seconds(self):
        # Necessário para o modo "definir data/hora exata", onde o
        # delta calculado raramente é um número redondo de horas.
        delta = timedelta(hours=4, minutes=28, seconds=29)
        assert build_exiftool_shift_expr(delta) == "+=0:0:0 4:28:29"

    def test_negative_sub_hour_precision(self):
        delta = timedelta(hours=-1, minutes=-30)
        assert build_exiftool_shift_expr(delta) == "-=0:0:0 1:30:0"

    def test_zero_delta(self):
        assert build_exiftool_shift_expr(timedelta(0)) == "+=0:0:0 0:0:0"


class TestFormatTimedelta:
    def test_hours_only(self):
        assert format_timedelta(timedelta(hours=3)) == "+3h"

    def test_negative_hours(self):
        assert format_timedelta(timedelta(hours=-5)) == "-5h"

    def test_days_and_hours(self):
        assert format_timedelta(timedelta(days=1, hours=3)) == "+1d 3h"

    def test_full_precision(self):
        delta = timedelta(hours=4, minutes=28, seconds=29)
        assert format_timedelta(delta) == "+4h 28min 29s"

    def test_zero_shows_zero_seconds(self):
        assert format_timedelta(timedelta(0)) == "+0s"

    def test_omits_zeroed_components(self):
        # 2 dias exatos não deveria mostrar "0h 0min 0s" no meio.
        assert format_timedelta(timedelta(days=2)) == "+2d"


class TestParseTargetDatetime:
    REFERENCE = datetime(2026, 6, 17, 11, 18, 21)

    def test_full_date_and_time_with_seconds(self):
        result = parse_target_datetime("17/06/2026 12:18:21", self.REFERENCE)
        assert result == datetime(2026, 6, 17, 12, 18, 21)

    def test_full_date_and_time_without_seconds(self):
        result = parse_target_datetime("17/06/2026 12:18", self.REFERENCE)
        assert result == datetime(2026, 6, 17, 12, 18, 0)

    def test_different_date_than_reference(self):
        # Caso a DATA também esteja errada, não só a hora.
        result = parse_target_datetime("18/06/2026 09:00:00", self.REFERENCE)
        assert result == datetime(2026, 6, 18, 9, 0, 0)

    def test_only_time_keeps_reference_date(self):
        result = parse_target_datetime("15:45:26", self.REFERENCE)
        assert result == datetime(2026, 6, 17, 15, 45, 26)

    def test_only_time_without_seconds_keeps_reference_date(self):
        result = parse_target_datetime("15:45", self.REFERENCE)
        assert result == datetime(2026, 6, 17, 15, 45, 0)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_target_datetime("", self.REFERENCE)

    def test_garbage_raises(self):
        with pytest.raises(ValueError):
            parse_target_datetime("não é uma data", self.REFERENCE)


class TestRunSetExactDatetimeFlow:
    """Integração do fluxo da opção 3: o delta deve ser calculado a
    partir da diferença entre a data digitada e a data ATUAL do
    arquivo de referência (o primeiro da lista), e esse MESMO delta
    aplicado a todos os arquivos selecionados."""

    def test_computes_delta_from_reference_file_and_applies_to_all(self, tmp_path):
        f1 = tmp_path / "a_video1.mp4"
        f2 = tmp_path / "b_video2.mp4"
        f1.write_bytes(b"x")
        f2.write_bytes(b"x")

        reference_dt = datetime(2026, 6, 17, 11, 18, 21)
        target_dt = datetime(2026, 6, 17, 12, 18, 21)  # usuário digita +1h

        with patch(
            "media_datetime_shift.ask_target_files", return_value=[str(f1), str(f2)]
        ), patch(
            "media_datetime_shift.read_primary_datetime", return_value=reference_dt
        ), patch(
            "media_datetime_shift.ask_target_datetime", return_value=target_dt
        ), patch(
            "media_datetime_shift.confirm", side_effect=[False, True, True]
            # dry_run=False, keep_backup=True, confirma=True
        ), patch(
            "media_datetime_shift.process_files"
        ) as mock_process:
            run_set_exact_datetime_flow(has_setfile=False)

        mock_process.assert_called_once()
        call_args = mock_process.call_args[0]
        assert call_args[0] == [str(f1), str(f2)]
        assert call_args[1] == timedelta(hours=1)

    def test_aborts_when_reference_file_has_no_exif_date(self, tmp_path):
        f1 = tmp_path / "video.mp4"
        f1.write_bytes(b"x")

        with patch(
            "media_datetime_shift.ask_target_files", return_value=[str(f1)]
        ), patch(
            "media_datetime_shift.read_primary_datetime", return_value=None
        ), patch(
            "media_datetime_shift.process_files"
        ) as mock_process:
            run_set_exact_datetime_flow(has_setfile=False)

        mock_process.assert_not_called()

    def test_aborts_when_target_equals_reference(self, tmp_path):
        f1 = tmp_path / "video.mp4"
        f1.write_bytes(b"x")
        same_dt = datetime(2026, 6, 17, 11, 18, 21)

        with patch(
            "media_datetime_shift.ask_target_files", return_value=[str(f1)]
        ), patch(
            "media_datetime_shift.read_primary_datetime", return_value=same_dt
        ), patch(
            "media_datetime_shift.ask_target_datetime", return_value=same_dt
        ), patch(
            "media_datetime_shift.process_files"
        ) as mock_process:
            run_set_exact_datetime_flow(has_setfile=False)

        mock_process.assert_not_called()


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
