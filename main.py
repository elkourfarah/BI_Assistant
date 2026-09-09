from __future__ import annotations

# ---------------------------------------------------------------------------
# Auto-activation du virtualenv
# Si le script est lancé avec le Python système (sans activer le venv),
# il se relance automatiquement avec l'interpréteur du venv.
# ---------------------------------------------------------------------------
import os
import subprocess
import sys
from pathlib import Path as _Path

_VENV_PYTHON = _Path(__file__).resolve().parent / "venv" / "Scripts" / "python.exe"
if _VENV_PYTHON.exists() and _Path(sys.executable).resolve() != _VENV_PYTHON.resolve():
    result = subprocess.run([str(_VENV_PYTHON)] + sys.argv)
    sys.exit(result.returncode)
# ---------------------------------------------------------------------------

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.builders.document_builder import DocumentBuilder
from src.extractors import (
    BatchExtractionResult,
    ExcelExtractor,
    InputProcessor,
    PBIXExtractor,
    SQLExtractor,
)
from src.extractors.sql_extractor import ETLPackageMeta
from src.llm import GroqClient
from src.models import Table
from src.rag import STDRetriever
from src.reasoning import HybridReasoner
from src.sections import ProjectMetadata

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assistant BI Keyrus – Génère la documentation STD à partir de fichiers PBIX, SQL, Excel et archives ZIP.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples :\n"
            "  python main.py --zip paquet_client.zip\n"
            "  python main.py --input dossier_donnees/ script_dwh.sql\n"
            "  python main.py --excel spec_mapping.xlsx compo_donnees.csv\n"
            "  python main.py --pbix rapport.pbix --sql scripts/\n"
            "  python main.py --sql DWH_UCMS.sql DWH_CRM.sql --force\n"
        ),
    )
    parser.add_argument(
        "--input", "-i",
        nargs="+",
        default=None,
        help="Un ou plusieurs fichiers, dossiers ou archives ZIP (détection automatique des types).",
    )
    parser.add_argument(
        "--zip", "-z",
        nargs="+",
        default=None,
        help="Une ou plusieurs archives .zip d'entrée.",
    )
    parser.add_argument(
        "--excel", "-e",
        nargs="+",
        default=None,
        help="Un ou plusieurs fichiers .xlsx, .xls, .csv ou dossiers contenant des fichiers Excel.",
    )
    parser.add_argument(
        "--pbix",
        nargs="+",
        default=None,
        help="Un ou plusieurs fichiers .pbix.",
    )
    parser.add_argument(
        "--sql",
        nargs="+",
        default=None,
        help="Un ou plusieurs fichiers .sql ou dossiers contenant des fichiers .sql.",
    )
    parser.add_argument(
        "--output", default="output",
        help="Dossier de sortie (défaut: output/)",
    )
    parser.add_argument(
        "--model", default=None,
        help="Modèle Groq à utiliser",
    )
    parser.add_argument(
        "--dialect",
        default="oracle",
        help="Dialecte SQL pour sqlglot (défaut: oracle). Ex: snowflake, spark, postgres",
    )
    parser.add_argument(
        "--project",
        default="Projet BI",
        help="Nom du projet (apparaît sur la page de garde)",
    )
    parser.add_argument(
        "--strict",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Mode strict (défaut: activé). Si activé, affiche 'Aucun mapping détecté' "
             "plutôt que d'inventer du contenu fictif.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Force la génération même si les fichiers sont détectés comme incompatibles. "
             "Un avertissement sera ajouté en tête du document.",
    )
    parser.add_argument(
        "--images",
        nargs="+",
        default=None,
        metavar="IMAGE",
        help="Images à inclure dans les Annexes du document (PNG, JPG, etc.). "
             "Exemple : --images schema_architecture.png capture_rapport.png",
    )
    parser.add_argument(
        "--rag-template",
        default=None,
        metavar="DOCX",
        help="Fichier Word template STD à utiliser pour le RAG "
             "(défaut: STD-SI-PERFORMANCE-xxxxx-V0.1.docx dans le répertoire courant).",
    )
    return parser


# ---------------------------------------------------------------------------
# Helpers I/O
# ---------------------------------------------------------------------------


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# Reasoning : compatibilité des fichiers
# ---------------------------------------------------------------------------


def _run_reasoning(
    sql_paths: list[Path],
    pbix_paths: list[Path],
    excel_paths: list[Path],
    sql_metadata_list: list[dict],
    pbix_metadata: dict | None,
    excel_metadata_list: list[dict],
    pbix_tables: list | None = None,
    llm_client: Any = None,
    force: bool = False,
) -> tuple[bool, str, str, str]:
    """Construit les ontologies et évalue la compatibilité via HybridReasoner."""
    reasoner = HybridReasoner(llm_client=llm_client)

    sql_inputs = []
    for i, pkg in enumerate(sql_metadata_list):
        path_str = str(sql_paths[i]) if i < len(sql_paths) else f"sql_file_{i}.sql"
        sql_inputs.append((path_str, pkg))

    pbix_inputs = []
    for i, path in enumerate(pbix_paths):
        pbix_inputs.append((str(path), pbix_metadata, pbix_tables))

    excel_inputs = []
    for i, meta in enumerate(excel_metadata_list):
        path_str = str(excel_paths[i]) if i < len(excel_paths) else f"excel_file_{i}.xlsx"
        excel_inputs.append((path_str, meta))

    report = reasoner.evaluate_files(
        sql_inputs=sql_inputs,
        pbix_inputs=pbix_inputs,
        excel_inputs=excel_inputs,
    )

    if report.detailed_report:
        print(report.detailed_report)

    incompatibility_banner = ""

    if not report.is_compatible:
        if force:
            LOGGER.warning(
                "--force activé : génération forcée malgré l'incompatibilité détectée."
            )
            incompatibility_banner = (
                "> ⚠️ **AVERTISSEMENT : Fichiers potentiellement incompatibles**\n"
                ">\n"
                "> Les fichiers fournis ont été détectés comme appartenant à des domaines "
                "fonctionnels différents. Ce document a été généré avec `--force` et peut "
                "contenir des incohérences. Vérifiez la cohérence du contenu avant diffusion.\n"
            )
        else:
            return False, report.dominant_domain, report.dominant_label, ""

    return True, report.dominant_domain, report.dominant_label, incompatibility_banner


# ---------------------------------------------------------------------------
# RAG : initialisation du retriever
# ---------------------------------------------------------------------------


def _build_rag_retriever(
    rag_template_path: Path | None,
    sql_paths: list[Path],
    project_root: Path,
) -> STDRetriever:
    """Initialise le retriever RAG avec le template Word STD et les SQL de référence."""
    word_path: Path | None = None
    if rag_template_path:
        word_path = rag_template_path
    else:
        default_candidates = list(project_root.glob("STD-SI-*.docx")) + list(project_root.glob("STD-*.docx"))
        if default_candidates:
            word_path = default_candidates[0]
            LOGGER.info("Template STD RAG auto-détecté : %s", word_path.name)

    word_paths = [word_path] if word_path and word_path.exists() else []
    all_sql_candidates = list(project_root.glob("*.sql"))
    sql_rag_paths = list({p.resolve() for p in (sql_paths + all_sql_candidates) if p.exists()})

    retriever = STDRetriever.build(
        word_paths=word_paths,
        sql_paths=sql_rag_paths,
    )
    LOGGER.info(
        "RAG initialisé : %d chunks indexés (%s, %d SQL files)",
        len(retriever._store.chunks),
        word_path.name if word_path else "aucun template Word",
        len(sql_rag_paths),
    )
    return retriever


# ---------------------------------------------------------------------------
# Orchestrateur principal
# ---------------------------------------------------------------------------


def main() -> int:
    """Point d'entrée principal de l'assistant BI."""
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=env_path, override=False)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logging.getLogger("sqlglot").setLevel(logging.CRITICAL)

    parser = _build_parser()
    args = parser.parse_args()

    if not args.pbix and not args.sql and not args.excel and not args.zip and not args.input:
        parser.error("Au moins un fichier/dossier d'entrée doit être spécifié (--input, --zip, --excel, --sql, --pbix).")

    project_root = Path(__file__).resolve().parent
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # ---- Processing & Extraction par lot (Multi-Fichiers / ZIP) ----

    processor = InputProcessor()

    try:
        targets: list[str] = []
        if args.input:
            targets.extend(args.input)
        if args.zip:
            targets.extend(args.zip)

        batch_res: BatchExtractionResult = processor.process_all(
            targets=targets,
            dialect=args.dialect,
            explicit_sql=args.sql,
            explicit_pbix=args.pbix,
            explicit_excel=args.excel,
            explicit_images=args.images,
        )

        if batch_res.pbix_metadata:
            _write_json(output_dir / "metadatas.json", batch_res.pbix_metadata)
            LOGGER.info("Métadonnées PBIX écrites dans %s", output_dir / "metadatas.json")

        if batch_res.sql_metadata_list:
            _write_json(output_dir / "sql_metadata.json", batch_res.sql_metadata_list)
            LOGGER.info("Métadonnées SQL écrites dans %s", output_dir / "sql_metadata.json")

        if batch_res.excel_metadata_list:
            _write_json(output_dir / "excel_metadata.json", batch_res.excel_metadata_list)
            LOGGER.info("Métadonnées Excel écrites dans %s", output_dir / "excel_metadata.json")

        # ---- Client LLM ----

        llm_client: GroqClient | None = None
        try:
            llm_client = GroqClient(model=args.model)
        except RuntimeError as exc:
            LOGGER.warning("Initialisation du client LLM pour reasoning non effectuée: %s", exc)

        # ---- Reasoning : vérification de la compatibilité ----

        LOGGER.info("[Reasoning] Vérification de la compatibilité des fichiers fournis...")
        compatible, dominant_domain, dominant_label, incompatibility_banner = _run_reasoning(
            sql_paths=batch_res.sql_paths,
            pbix_paths=batch_res.pbix_paths,
            excel_paths=batch_res.excel_paths,
            sql_metadata_list=batch_res.sql_metadata_list,
            pbix_metadata=batch_res.pbix_metadata,
            excel_metadata_list=batch_res.excel_metadata_list,
            pbix_tables=batch_res.pbix_tables,
            llm_client=llm_client,
            force=args.force,
        )

        if not compatible:
            LOGGER.error(
                "[ERREUR] Fichiers incompatibles. Utilisez --force pour générer quand même."
            )
            return 1

        LOGGER.info("[OK] Compatibilité validée -- Domaine : %s", dominant_label)

        # ---- RAG : initialisation du template STD ----

        LOGGER.info("[RAG] Initialisation (template STD + patterns SQL)...")
        rag_template_path: Path | None = None
        if args.rag_template:
            rag_template_path = Path(args.rag_template).expanduser().resolve()

        retriever = _build_rag_retriever(
            rag_template_path=rag_template_path,
            sql_paths=batch_res.sql_paths,
            project_root=project_root,
        )

        if llm_client is None:
            try:
                llm_client = GroqClient(model=args.model)
            except RuntimeError as exc:
                LOGGER.error("Initialisation du client LLM échouée: %s", exc)
                return 1

        # ---- Construction des métadonnées pivot ----

        input_file_names = _collect_input_files(args, batch_res)

        metadata = ProjectMetadata(
            tables=batch_res.tables,
            pbix_metadata=batch_res.pbix_metadata,
            sql_metadata=batch_res.sql_metadata_list,
            excel_metadata=batch_res.excel_metadata_list,
            excel_tables=batch_res.excel_tables,
            project_name=args.project,
            strict=args.strict,
            dominant_domain=dominant_domain,
            dominant_label=dominant_label,
            incompatibility_banner=incompatibility_banner,
            input_files=input_file_names,
        ).compute()

        total_mappings = metadata.total_mapping_count
        LOGGER.info("%d règle(s) de mapping extraite(s) au total.", total_mappings)
        if total_mappings == 0 and args.strict:
            LOGGER.warning(
                "Mode strict : aucun mapping détecté. "
                "Le document affichera un avertissement explicite dans la section Mapping."
            )

        # ---- Orchestration via DocumentBuilder ----

        doc_path = output_dir / "documentation_finale.docx"
        saved_doc = DocumentBuilder(llm_client, retriever=retriever).build(
            metadata=metadata,
            output_path=doc_path,
            project_name=args.project,
            user_images=batch_res.user_images,
        )

        LOGGER.info("[OK] Documentation générée avec succès : %s", saved_doc)
        LOGGER.info("[INFO] Artefacts disponibles dans : %s", output_dir)
        return 0

    finally:
        processor.cleanup()


def _collect_input_files(args: argparse.Namespace, batch_res: BatchExtractionResult | None = None) -> list[str]:
    """Construit la liste lisible des fichiers fournis en entrée pour la page de garde."""
    files: list[str] = []
    if batch_res and batch_res.input_descriptions:
        return batch_res.input_descriptions

    if args.zip:
        for z in args.zip:
            files.append(f"{Path(z).name} (Archive ZIP)")
    if args.excel:
        for e in args.excel:
            files.append(f"{Path(e).name} (Excel / CSV)")
    if args.pbix:
        for p in args.pbix:
            files.append(f"{Path(p).name} (Power BI)")
    if args.sql:
        for s in args.sql:
            p = Path(s)
            files.append(f"{p.name}/ (dossier SQL)" if p.is_dir() else f"{p.name} (SQL)")
    return files


if __name__ == "__main__":
    raise SystemExit(main())