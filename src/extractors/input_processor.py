"""Processeur d'entrées d'entreprise (Multi-Fichiers, Archives ZIP/RAR/7Z, Dossiers et Auto-découverte)."""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models.table import Table
from .excel_extractor import ExcelExtractor
from .pbix_extractor import PBIXExtractor
from .sql_extractor import ETLPackageMeta, SQLExtractor

LOGGER = logging.getLogger(__name__)

_SUPPORTED_SQL_EXT = {".sql"}
_SUPPORTED_PBIX_EXT = {".pbix"}
_SUPPORTED_EXCEL_EXT = {".xlsx", ".xls", ".xlsm", ".csv"}
_SUPPORTED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".svg", ".webp", ".bmp"}
_SUPPORTED_ARCHIVE_EXT = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz"}


@dataclass
class DiscoveredInputs:
    """Structure représentant tous les fichiers découverts par type."""

    sql_files: list[Path] = field(default_factory=list)
    pbix_files: list[Path] = field(default_factory=list)
    excel_files: list[Path] = field(default_factory=list)
    image_files: list[Path] = field(default_factory=list)
    archive_files: list[Path] = field(default_factory=list)
    temp_dirs: list[Path] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.sql_files or self.pbix_files or self.excel_files or self.image_files)


@dataclass
class BatchExtractionResult:
    """Résultats agrégés de l'extraction par lot de l'ensemble des fichiers."""

    tables: list[Table] = field(default_factory=list)
    pbix_metadata: dict[str, Any] | None = None
    pbix_tables: list[Table] = field(default_factory=list)
    pbix_paths: list[Path] = field(default_factory=list)

    sql_packages: list[ETLPackageMeta] = field(default_factory=list)
    sql_metadata_list: list[dict[str, Any]] = field(default_factory=list)
    sql_paths: list[Path] = field(default_factory=list)

    excel_tables: list[Table] = field(default_factory=list)
    excel_metadata_list: list[dict[str, Any]] = field(default_factory=list)
    excel_paths: list[Path] = field(default_factory=list)

    user_images: list[Path] = field(default_factory=list)
    input_descriptions: list[str] = field(default_factory=list)


class InputProcessor:
    """Gère l'extraction sécurisée de fichiers ZIP, RAR, 7Z, le parcours de répertoires et l'auto-découverte."""

    def __init__(self) -> None:
        self._created_temp_dirs: list[Path] = []

    def cleanup(self) -> None:
        """Nettoie les répertoires temporaires créés lors de la décompression d'archives."""
        for tmp in self._created_temp_dirs:
            if tmp.exists():
                try:
                    shutil.rmtree(tmp, ignore_errors=True)
                    LOGGER.info("Répertoire temporaire nettoyé : %s", tmp)
                except Exception as exc:
                    LOGGER.warning("Impossible de supprimer le dossier temporaire %s : %s", tmp, exc)
        self._created_temp_dirs.clear()

    def discover(self, targets: list[str | Path]) -> DiscoveredInputs:
        """Parcourt la liste des cibles (fichiers, répertoires, archives ZIP/RAR) et classe les fichiers trouvés.

        Args:
            targets: Liste de chemins (chaînes ou Path).

        Returns:
            DiscoveredInputs contenant tous les fichiers classés par type.
        """
        discovered = DiscoveredInputs()

        for raw_target in targets:
            target_path = Path(raw_target).expanduser().resolve()
            if not target_path.exists():
                # Recherche intelligente : si le chemin relatif complet a été omis (ex: juste le nom de fichier)
                filename = Path(raw_target).name
                candidate = None
                samples_dir = Path.cwd() / "samples"
                if samples_dir.exists():
                    matches = list(samples_dir.rglob(filename))
                    if matches:
                        candidate = matches[0]
                if not candidate:
                    matches = [p for p in Path.cwd().rglob(filename) if "venv" not in p.parts and ".git" not in p.parts and ".pytest_cache" not in p.parts]
                    if matches:
                        candidate = matches[0]

                if candidate and candidate.exists():
                    LOGGER.info("Chemin auto-résolu : '%s' -> '%s'", raw_target, candidate)
                    target_path = candidate
                else:
                    LOGGER.warning("Cible introuvable (ignorée) : %s", raw_target)
                    continue

            if target_path.is_file():
                self._classify_file(target_path, discovered)
            elif target_path.is_dir():
                self._scan_directory(target_path, discovered)

        # Décompresser toutes les archives découvertes (.zip, .rar, .7z, etc.)
        while discovered.archive_files:
            arch_path = discovered.archive_files.pop()
            extracted_dir = self._extract_archive(arch_path)
            if extracted_dir:
                discovered.temp_dirs.append(extracted_dir)
                self._created_temp_dirs.append(extracted_dir)
                self._scan_directory(extracted_dir, discovered)

        return discovered

    def process_all(
        self,
        targets: list[str | Path],
        dialect: str = "oracle",
        explicit_sql: list[str | Path] | None = None,
        explicit_pbix: list[str | Path] | None = None,
        explicit_excel: list[str | Path] | None = None,
        explicit_images: list[str | Path] | None = None,
    ) -> BatchExtractionResult:
        """Extrait et agrège toutes les métadonnées issues des fichiers fournis.

        Args:
            targets: Chemins généraux (fichiers, répertoires, archives).
            dialect: Dialecte SQL pour sqlglot.
            explicit_sql: Liste explicite de fichiers SQL.
            explicit_pbix: Liste explicite de fichiers PBIX.
            explicit_excel: Liste explicite de fichiers Excel.
            explicit_images: Liste explicite d'images.

        Returns:
            BatchExtractionResult structuré.

        Raises:
            RuntimeError: Si aucune donnée valide n'est extraite.
        """
        all_targets: list[str | Path] = list(targets)
        if explicit_sql:
            all_targets.extend(explicit_sql)
        if explicit_pbix:
            all_targets.extend(explicit_pbix)
        if explicit_excel:
            all_targets.extend(explicit_excel)
        if explicit_images:
            all_targets.extend(explicit_images)

        discovered = self.discover(all_targets)

        if discovered.is_empty():
            raise RuntimeError(
                f"Aucun fichier BI valide (.sql, .pbix, .xlsx, .csv) n'a pu être découvert ou extrait des cibles : {all_targets}"
            )

        result = BatchExtractionResult()

        # 1. Extraction SQL
        if discovered.sql_files:
            sql_extractor = SQLExtractor(dialect=dialect)
            for sql_path in discovered.sql_files:
                try:
                    pkgs = sql_extractor.extract_from_file(sql_path) if sql_path.is_file() else sql_extractor.extract_from_directory(sql_path)
                    pkg_list = pkgs if isinstance(pkgs, list) else [pkgs]
                    for pkg in pkg_list:
                        result.sql_packages.append(pkg)
                        result.sql_metadata_list.append(sql_extractor.to_dict(pkg))
                        result.sql_paths.append(sql_path)
                    LOGGER.info("SQL extrait avec succès : %s", sql_path.name)
                except Exception as exc:
                    LOGGER.error("Erreur lors de l'extraction SQL de %s : %s", sql_path.name, exc)

            result.input_descriptions.append(f"{len(discovered.sql_files)} fichier(s) SQL")

        # 2. Extraction PBIX
        if discovered.pbix_files:
            for pbix_path in discovered.pbix_files:
                try:
                    extractor = PBIXExtractor(pbix_path)
                    p_tables = extractor.extract()
                    result.tables.extend(p_tables)
                    result.pbix_tables.extend(p_tables)
                    result.pbix_paths.append(pbix_path)

                    if result.pbix_metadata is None:
                        result.pbix_metadata = extractor.raw_metadata
                    elif extractor.raw_metadata and "tables" in result.pbix_metadata:
                        result.pbix_metadata["tables"].extend(extractor.raw_metadata.get("tables", []))

                    LOGGER.info("PBIX extrait avec succès : %s", pbix_path.name)
                except Exception as exc:
                    LOGGER.error("Erreur lors de l'extraction PBIX de %s : %s", pbix_path.name, exc)

            result.input_descriptions.append(f"{len(discovered.pbix_files)} fichier(s) Power BI (.pbix)")

        # 3. Extraction Excel / CSV
        if discovered.excel_files:
            for excel_path in discovered.excel_files:
                try:
                    extractor = ExcelExtractor(excel_path)
                    e_tables, e_meta = extractor.extract()
                    result.excel_tables.extend(e_tables)
                    result.excel_metadata_list.append(e_meta)
                    result.excel_paths.append(excel_path)
                    result.tables.extend(e_tables)
                    LOGGER.info("Excel/CSV extrait avec succès : %s", excel_path.name)
                except Exception as exc:
                    LOGGER.error("Erreur lors de l'extraction Excel de %s : %s", excel_path.name, exc)

            result.input_descriptions.append(f"{len(discovered.excel_files)} fichier(s) Excel / CSV")

        # 4. Images utilisateur
        result.user_images = discovered.image_files

        return result

    def _classify_file(self, file_path: Path, discovered: DiscoveredInputs) -> None:
        ext = file_path.suffix.lower()
        if ext in _SUPPORTED_SQL_EXT:
            if file_path not in discovered.sql_files:
                discovered.sql_files.append(file_path)
        elif ext in _SUPPORTED_PBIX_EXT:
            if file_path not in discovered.pbix_files:
                discovered.pbix_files.append(file_path)
        elif ext in _SUPPORTED_EXCEL_EXT:
            if file_path not in discovered.excel_files:
                discovered.excel_files.append(file_path)
        elif ext in _SUPPORTED_IMAGE_EXT:
            if file_path not in discovered.image_files:
                discovered.image_files.append(file_path)
        elif ext in _SUPPORTED_ARCHIVE_EXT:
            if file_path not in discovered.archive_files:
                discovered.archive_files.append(file_path)

    def _scan_directory(self, dir_path: Path, discovered: DiscoveredInputs) -> None:
        for root, _, files in os.walk(dir_path):
            for file_name in files:
                fpath = Path(root) / file_name
                self._classify_file(fpath, discovered)

    def _extract_archive(self, archive_path: Path) -> Path | None:
        """Extrait de manière sécurisée tout type d'archive (.zip, .rar, .7z, .tar) dans un dossier temporaire."""
        ext = archive_path.suffix.lower()
        tmp_dir = Path(tempfile.mkdtemp(prefix="bi_assistant_arch_"))
        LOGGER.info("Décompaction de l'archive %s (%s) vers %s", archive_path.name, ext, tmp_dir)

        # 1. ZIP via zipfile
        if ext == ".zip":
            try:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    for member in zf.infolist():
                        m_path = Path(member.filename)
                        if m_path.is_absolute() or ".." in m_path.parts:
                            continue
                        zf.extract(member, tmp_dir)
                return tmp_dir
            except Exception as exc:
                LOGGER.warning("zipfile standard a échoué pour %s : %s", archive_path.name, exc)

        # 2. 7Z via py7zr
        if ext == ".7z":
            try:
                import py7zr
                with py7zr.SevenZipFile(archive_path, mode="r") as z:
                    z.extractall(path=tmp_dir)
                return tmp_dir
            except Exception as exc:
                LOGGER.warning("py7zr a échoué pour %s : %s", archive_path.name, exc)

        # 3. Universal via patoolib (gère .rar, .7z, .zip, .tar, etc.)
        try:
            import patoolib
            patoolib.extract_archive(str(archive_path), outdir=str(tmp_dir), verbosity=-1)
            return tmp_dir
        except Exception as exc:
            LOGGER.warning("patoolib a échoué pour %s : %s", archive_path.name, exc)

        # 4. Fallback via shutil
        try:
            shutil.unpack_archive(str(archive_path), str(tmp_dir))
            return tmp_dir
        except Exception as exc:
            LOGGER.error("Impossible de décompresser l'archive %s : %s", archive_path.name, exc)

        return None
