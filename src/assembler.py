from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

LOGGER = logging.getLogger(__name__)

# Couleur de l'en-tête des tableaux (bleu Keyrus)
_HEADER_BG = "003087"
_HEADER_FG = "FFFFFF"
_ALT_ROW_BG = "E8EEF8"


class DocumentAssembler:
    """Assemble un document Word STD complet à partir des sections Markdown générées."""

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Point d'entrée principal (STD complet)
    # ------------------------------------------------------------------

    def assemble_std(
        self,
        *,
        sections: list[tuple[str, str]],  # [(section_id, markdown), ...]
        executive_summary_markdown: str = "",
        glossary_markdown: str = "",
        diagram_path: str | Path | None = None,
        mermaid_code: str = "",
        output_path: str | Path,
        project_name: str = "Projet BI",
        input_files: list[str] | None = None,
        dominant_label: str = "",
        user_images: list[Path] | None = None,
    ) -> Path:
        """Génère le document Word STD structuré selon le template Keyrus.

        Args:
            sections: Liste ordonnée de tuples (title, markdown). Seules les sections
                      avec un contenu non vide sont insérées.
            executive_summary_markdown: Résumé exécutif optionnel.
            glossary_markdown: Glossaire optionnel.
            diagram_path: Chemin vers le PNG du diagramme de lineage.
            mermaid_code: Code Mermaid brut (fallback si PNG indisponible).
            output_path: Chemin de sortie du fichier .docx.
            project_name: Nom du projet pour la page de garde.
            input_files: Liste des fichiers source fournis.
            dominant_label: Domaine métier détecté.
            user_images: Images fournies par l'utilisateur.

        Returns:
            Chemin effectif du fichier Word sauvegardé.
        """
        from datetime import datetime

        output_file = Path(output_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        versioned_name = f"{output_file.stem}_{timestamp}{output_file.suffix}"
        versioned_path = output_file.with_name(versioned_name)

        document = Document()
        self._configure_page(document, project_name=project_name)
        self._configure_fonts(document)

        # Filtrer les sections vides
        active_sections = [(title, md) for title, md in sections if md and md.strip()]

        # Page de garde
        self._add_cover_page(
            document, project_name,
            input_files=input_files or [],
            dominant_label=dominant_label,
        )

        # Table des matières dynamique basée sur les sections actives
        self._add_table_of_contents(
            document,
            active_sections=active_sections,
            has_exec_summary=bool(executive_summary_markdown),
            has_glossary=bool(glossary_markdown),
            has_diagram=bool(diagram_path or mermaid_code),
            has_user_images=bool(user_images),
        )

        # Résumé Exécutif
        if executive_summary_markdown:
            self._add_section_content(document, executive_summary_markdown)

        # Corps du document : sections actives dans l'ordre
        for title, md in active_sections:
            self._add_section_content(document, md, fallback_title=title)

        # Annexes
        diagram_available = bool(
            diagram_path
            and Path(diagram_path).exists()
            and Path(diagram_path).stat().st_size > 1000
        )
        has_annexes = diagram_available or bool(mermaid_code) or bool(glossary_markdown) or bool(user_images)

        if has_annexes:
            document.add_heading("Annexes", level=1)

            document.add_heading("A1. Diagramme de Lineage (STG → DWH)", level=2)
            if diagram_available:
                try:
                    # Calibrage dynamique des dimensions de l'image (max 5.5 po de large, max 3.8 po de haut)
                    target_width = Inches(5.5)
                    target_height = None
                    try:
                        import struct
                        with open(diagram_path, "rb") as f_img:
                            header = f_img.read(24)
                            if header.startswith(b"\x89PNG\r\n\x1a\n"):
                                w_px, h_px = struct.unpack(">LL", header[16:24])
                                if w_px > 0 and h_px > 0:
                                    aspect = h_px / w_px
                                    if aspect > (3.8 / 5.5):
                                        target_height = Inches(3.8)
                                        target_width = None
                    except Exception:
                        target_width = Inches(5.5)

                    if target_height:
                        document.add_picture(str(diagram_path), height=target_height)
                    else:
                        document.add_picture(str(diagram_path), width=target_width)

                    # Centrage esthétique du visuel
                    if document.paragraphs:
                        document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

                    note_para = document.add_paragraph(
                        "Note : Le diagramme synthétique ci-dessus présente les flux de données principaux. "
                        "Les tables STG sont détaillées dans la Section Staging."
                    )
                    note_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    if note_para.runs:
                        note_para.runs[0].font.name = "Arial"
                        note_para.runs[0].font.size = Pt(9.5)
                        note_para.runs[0].font.italic = True
                    LOGGER.info("Diagramme PNG inséré : %s", diagram_path)
                except Exception as exc:
                    LOGGER.warning("Impossible d'insérer le diagramme PNG: %s", exc)
                    diagram_available = False

            if not diagram_available and mermaid_code:
                document.add_paragraph(
                    "Exportez ce code sur https://mermaid.live/ pour visualiser le diagramme."
                )
                code_text = f"```mermaid\n{mermaid_code}\n```"
                code_para = document.add_paragraph(code_text)
                try:
                    code_para.style = document.styles["No Spacing"]
                except KeyError:
                    code_para.style = document.styles["Normal"]
                run = code_para.runs[0] if code_para.runs else code_para.add_run(code_text)
                run.font.name = "Courier New"
                run.font.size = Pt(8)
                LOGGER.info("Code Mermaid inséré comme fallback dans le document Word.")

            if glossary_markdown:
                document.add_heading("A2. Glossaire des termes métier", level=2)
                self._render_markdown(document, glossary_markdown)

            if user_images:
                document.add_heading("A3. Visuels fournis", level=2)
                for img_idx, img_path in enumerate(user_images, start=1):
                    try:
                        img_para = document.add_paragraph()
                        img_para.add_run(f"Figure {img_idx} — {img_path.name}").bold = True
                        document.add_picture(str(img_path), width=Inches(5.5))
                        cap_para = document.add_paragraph(f"Figure {img_idx} : {img_path.stem}")
                        cap_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    except Exception as exc:
                        LOGGER.warning("Impossible d'insérer l'image %s : %s", img_path.name, exc)
                        document.add_paragraph(f"[Image non disponible : {img_path.name} — {exc}]")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        self._safe_save(document, versioned_path)
        LOGGER.info("Version horodatée sauvegardée : %s", versioned_path)

        saved_path = self._safe_save(document, output_file)
        LOGGER.info("Document STD généré : %s", saved_path)
        return saved_path

    # ------------------------------------------------------------------
    # Méthode de compatibilité descendante (ancienne API)
    # ------------------------------------------------------------------

    def assemble_std_legacy(
        self,
        *,
        intro_markdown: str,
        sources_markdown: str,
        staging_markdown: str,
        dwh_markdown: str,
        mapping_markdown: str,
        etl_markdown: str,
        performance_markdown: str = "",
        data_quality_markdown: str = "",
        security_markdown: str = "",
        monitoring_markdown: str,
        executive_summary_markdown: str = "",
        glossary_markdown: str = "",
        diagram_path: str | Path | None = None,
        mermaid_code: str = "",
        output_path: str | Path,
        project_name: str = "Projet BI",
        input_files: list[str] | None = None,
        dominant_label: str = "",
        user_images: list[Path] | None = None,
    ) -> Path:
        """Compatibilité avec l'ancienne interface à paramètres nommés fixes."""
        sections = [
            ("1. Introduction", intro_markdown),
            ("2. Sources de données", sources_markdown),
            ("3. Staging", staging_markdown),
            ("4. Data Warehouse (DWH)", dwh_markdown),
            ("5. Mapping Source → DWH", mapping_markdown),
            ("6. Alimentation des données (ETL)", etl_markdown),
            ("7. Volumétrie et Performances", performance_markdown),
            ("8. Qualité des données", data_quality_markdown),
            ("9. Sécurité", security_markdown),
            ("10. Monitoring et Traçabilité", monitoring_markdown),
        ]
        return self.assemble_std(
            sections=sections,
            executive_summary_markdown=executive_summary_markdown,
            glossary_markdown=glossary_markdown,
            diagram_path=diagram_path,
            mermaid_code=mermaid_code,
            output_path=output_path,
            project_name=project_name,
            input_files=input_files,
            dominant_label=dominant_label,
            user_images=user_images,
        )

    # ------------------------------------------------------------------
    # Sauvegarde sécurisée
    # ------------------------------------------------------------------

    def _safe_save(self, document: Document, output_file: Path) -> Path:
        """Sauvegarde le document Word en gérant les erreurs de permission."""
        from datetime import datetime

        try:
            document.save(str(output_file))
            return output_file
        except PermissionError:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stem = output_file.stem
            alt_path = output_file.with_name(f"{stem}_{timestamp}{output_file.suffix}")
            LOGGER.warning(
                "Impossible d'écrire '%s' (fichier ouvert dans Word ?). Sauvegarde vers '%s'.",
                output_file.name,
                alt_path.name,
            )
            document.save(str(alt_path))
            return alt_path
        except Exception as exc:
            raise RuntimeError(f"Impossible de sauvegarder le document Word : {exc}") from exc

    # ------------------------------------------------------------------
    # Page de garde
    # ------------------------------------------------------------------

    def _add_cover_page(
        self,
        document: Document,
        project_name: str,
        input_files: list[str] | None = None,
        dominant_label: str = "",
    ) -> None:
        """Ajoute une page de garde stylisée avec bandeau Keyrus, métadonnées et historique des révisions."""
        from datetime import datetime

        generation_date = datetime.now().strftime("%d/%m/%Y à %H:%M")

        document.add_paragraph()
        document.add_paragraph()
        title_para = document.add_paragraph()
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title_para.add_run("SPÉCIFICATION TECHNIQUE DÉTAILLÉE")
        run.bold = True
        run.font.name = "Arial"
        run.font.size = Pt(20)
        run.font.color.rgb = RGBColor(0, 48, 135)

        subtitle_para = document.add_paragraph()
        subtitle_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sub_run = subtitle_para.add_run(project_name)
        sub_run.font.name = "Arial"
        sub_run.font.size = Pt(14)
        sub_run.font.color.rgb = RGBColor(70, 130, 180)

        document.add_paragraph()

        # Nettoyage et formatage propre du label de domaine métier
        clean_dominant_label = dominant_label.strip() if dominant_label else ""
        if not clean_dominant_label or any(bad in clean_dominant_label.lower() for bad in ("non verifie", "inconnu", "unknown", "none")):
            clean_dominant_label = "Data Integration & Analytics"

        domain_para = document.add_paragraph()
        domain_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        d_run = domain_para.add_run(f"Domaine : {clean_dominant_label}")
        d_run.font.name = "Arial"
        d_run.font.size = Pt(12)
        d_run.italic = True
        d_run.font.color.rgb = RGBColor(100, 100, 100)
        document.add_paragraph()

        info_rows = [
            ("Projet", project_name),
            ("Domaine fonctionnel", clean_dominant_label),
            ("Document", "Spécification Technique Détaillée (STD)"),
            ("Date de génération", generation_date),
            ("Version", "1.0"),
            ("Auteur", "Assistant BI Keyrus"),
        ]

        info_table = document.add_table(rows=len(info_rows), cols=2)
        info_table.style = "Table Grid"

        for i, (label, value) in enumerate(info_rows):
            row = info_table.rows[i]
            label_cell = row.cells[0]
            label_cell.text = label
            label_para = label_cell.paragraphs[0]
            label_run = label_para.runs[0]
            label_run.bold = True
            label_run.font.name = "Arial"
            label_run.font.size = Pt(10)
            label_run.font.color.rgb = RGBColor(255, 255, 255)
            tc_pr = label_cell._tc.get_or_add_tcPr()
            shd = OxmlElement("w:shd")
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:color"), "auto")
            shd.set(qn("w:fill"), _HEADER_BG)
            tc_pr.append(shd)

            value_cell = row.cells[1]
            value_cell.text = value
            value_run = value_cell.paragraphs[0].runs[0]
            value_run.font.name = "Arial"
            value_run.font.size = Pt(10)

        document.add_paragraph()

        if input_files:
            files_heading = document.add_paragraph()
            fh_run = files_heading.add_run("Fichiers sources fournis :")
            fh_run.bold = True
            fh_run.font.name = "Arial"
            fh_run.font.size = Pt(10)
            fh_run.font.color.rgb = RGBColor(0, 48, 135)

            files_table = document.add_table(rows=len(input_files), cols=1)
            files_table.style = "Table Grid"
            for fi, fname in enumerate(input_files):
                cell = files_table.rows[fi].cells[0]
                cell.text = fname
                cell.paragraphs[0].runs[0].font.name = "Arial"
                cell.paragraphs[0].runs[0].font.size = Pt(10)
            document.add_paragraph()

        meta_para = document.add_paragraph()
        meta_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        meta_run = meta_para.add_run("Généré automatiquement par l'Assistant BI Keyrus")
        meta_run.font.name = "Arial"
        meta_run.font.size = Pt(10)
        meta_run.italic = True

        # ── Historique des révisions ──
        document.add_paragraph()
        rev_heading = document.add_paragraph()
        rh_run = rev_heading.add_run("Historique des révisions")
        rh_run.bold = True
        rh_run.font.name = "Arial"
        rh_run.font.size = Pt(10)
        rh_run.font.color.rgb = RGBColor(0, 48, 135)

        rev_table = document.add_table(rows=2, cols=4)
        rev_table.style = "Table Grid"
        rev_headers = ["Version", "Date", "Auteur", "Description"]
        for ci, hdr in enumerate(rev_headers):
            cell = rev_table.rows[0].cells[ci]
            cell.text = hdr
            run_h = cell.paragraphs[0].runs[0]
            run_h.bold = True
            run_h.font.name = "Arial"
            run_h.font.size = Pt(10)
            run_h.font.color.rgb = RGBColor(255, 255, 255)
            self._set_cell_bg(cell, _HEADER_BG)

        rev_values = ["1.0", generation_date, "Assistant BI Keyrus", "Génération initiale automatique"]
        for ci, val in enumerate(rev_values):
            cell = rev_table.rows[1].cells[ci]
            cell.text = val
            cell.paragraphs[0].runs[0].font.name = "Arial"
            cell.paragraphs[0].runs[0].font.size = Pt(10)
        document.add_paragraph()

        document.add_page_break()

    # ------------------------------------------------------------------
    # Table des matières dynamique
    # ------------------------------------------------------------------

    def _add_table_of_contents(
        self,
        document: Document,
        active_sections: list[tuple[str, str]],
        has_exec_summary: bool = False,
        has_glossary: bool = False,
        has_diagram: bool = False,
        has_user_images: bool = False,
    ) -> None:
        """Génère une Table des Matières Word native (champ TOC) avec numéros de page automatiques."""
        toc_heading = document.add_paragraph()
        toc_heading.style = document.styles["Heading 1"]
        toc_heading.add_run("Table des matières")

        # Paragraphe contenant le champ TOC Word natif
        toc_para = document.add_paragraph()
        toc_para.paragraph_format.space_before = Pt(4)
        toc_para.paragraph_format.space_after = Pt(4)
        run = toc_para.add_run()

        fldChar_begin = OxmlElement("w:fldChar")
        fldChar_begin.set(qn("w:fldCharType"), "begin")
        fldChar_begin.set(qn("w:dirty"), "true")
        run._r.append(fldChar_begin)

        instrText = OxmlElement("w:instrText")
        instrText.set(qn("xml:space"), "preserve")
        instrText.text = ' TOC \\o "1-3" \\h \\z \\u '
        run._r.append(instrText)

        fldChar_sep = OxmlElement("w:fldChar")
        fldChar_sep.set(qn("w:fldCharType"), "separate")
        run._r.append(fldChar_sep)

        fldChar_end = OxmlElement("w:fldChar")
        fldChar_end.set(qn("w:fldCharType"), "end")
        run._r.append(fldChar_end)

        note_para = document.add_paragraph()
        note_para.paragraph_format.space_before = Pt(6)
        note_r = note_para.add_run("ℹ️  Appuyez sur Ctrl+A puis F9 dans Word pour actualiser la table des matières.")
        note_r.font.name = "Arial"
        note_r.font.size = Pt(9)
        note_r.italic = True
        note_r.font.color.rgb = RGBColor(120, 120, 120)

        document.add_page_break()

    # ------------------------------------------------------------------
    # Section : contenu Markdown seulement (SANS ajouter un titre level=1 en double)
    # ------------------------------------------------------------------

    def _add_section_content(
        self,
        document: Document,
        markdown_text: str,
        fallback_title: str = "",
    ) -> None:
        """Insère le contenu Markdown d'une section.

        Si le Markdown commence par un titre (## ou #), il est rendu tel quel via _render_markdown.
        Si le Markdown ne commence pas par un titre et qu'un fallback_title est fourni, 
        on ajoute le titre comme heading level=1 avant le contenu.

        Cette méthode évite les titres dupliqués.
        """
        if not markdown_text or not markdown_text.strip():
            return

        first_non_empty = next(
            (line.strip() for line in markdown_text.splitlines() if line.strip()),
            "",
        )
        has_header = first_non_empty.startswith("#")

        if not has_header and fallback_title:
            document.add_heading(fallback_title, level=1)

        self._render_markdown(document, markdown_text)

    # ------------------------------------------------------------------
    # Rendu Markdown → Word
    # ------------------------------------------------------------------

    def _render_markdown(self, document: Document, markdown_text: str) -> None:
        """Convertit du Markdown en contenu Word structuré."""
        if not markdown_text:
            return
        lines = markdown_text.splitlines()
        idx = 0
        while idx < len(lines):
            line = lines[idx]
            stripped = line.strip()

            # Blocs de code → ignorer le contenu
            if stripped.startswith("```"):
                idx += 1
                while idx < len(lines) and not lines[idx].strip().startswith("```"):
                    idx += 1
                idx += 1
                continue

            # Titres (en retirant la numérotation si déjà présente dans le titre pour éviter les doublons)
            if stripped.startswith("#### "):
                document.add_heading(stripped[5:].strip(), level=4)
            elif stripped.startswith("### "):
                document.add_heading(stripped[4:].strip(), level=3)
            elif stripped.startswith("## "):
                document.add_heading(stripped[3:].strip(), level=2)
            elif stripped.startswith("# "):
                document.add_heading(stripped[2:].strip(), level=1)

            # Tableau Markdown
            elif stripped.startswith("|"):
                table_lines: list[str] = []
                while idx < len(lines) and lines[idx].strip().startswith("|"):
                    table_lines.append(lines[idx].strip())
                    idx += 1
                self._add_markdown_table(document, table_lines)
                continue

            # Liste à puces
            elif stripped.startswith("- ") or stripped.startswith("* "):
                para = document.add_paragraph(style="List Bullet")
                self._add_formatted_run(para, stripped[2:].strip())

            # Liste numérotée
            elif re.match(r"^\d+\. ", stripped):
                para = document.add_paragraph(style="List Number")
                content = re.sub(r"^\d+\. ", "", stripped)
                self._add_formatted_run(para, content)

            # Ligne séparatrice
            elif re.match(r"^-{3,}$|^\*{3,}$|^_{3,}$", stripped):
                pass

            # Ligne vide
            elif not stripped:
                pass

            # Paragraphe normal
            else:
                para = document.add_paragraph()
                self._add_formatted_run(para, stripped)

            idx += 1

    def _add_formatted_run(self, para: Any, text: str) -> None:
        """Ajoute un run avec support du gras (**texte**) et de l'italique (*texte*)."""
        pattern = re.compile(r"(\*\*.*?\*\*|\*.*?\*|`[^`]+`|[^*`]+)")
        for match in pattern.finditer(text):
            chunk = match.group(0)
            run = para.add_run()
            run.font.name = "Arial"
            run.font.size = Pt(11)
            if chunk.startswith("**") and chunk.endswith("**"):
                run.bold = True
                run.text = chunk[2:-2]
            elif chunk.startswith("*") and chunk.endswith("*") and not chunk.startswith("**"):
                run.italic = True
                run.text = chunk[1:-1]
            elif chunk.startswith("`") and chunk.endswith("`"):
                run.font.name = "Courier New"
                run.font.size = Pt(10)
                run.text = chunk[1:-1]
            else:
                run.text = chunk

    # ------------------------------------------------------------------
    # Tableaux Markdown → Word
    # ------------------------------------------------------------------

    def _add_markdown_table(self, document: Document, table_lines: list[str]) -> None:
        """Convertit un tableau Markdown en tableau Word formaté."""
        rows: list[list[str]] = []
        for line in table_lines:
            if re.match(r"^\|[-| :]+\|?$", line):
                continue
            cells = [c.strip() for c in line.split("|")]
            if cells and cells[0] == "":
                cells = cells[1:]
            if cells and cells[-1] == "":
                cells = cells[:-1]
            if cells:
                rows.append(cells)

        if not rows:
            return

        num_cols = max(len(row) for row in rows)
        if num_cols == 0:
            return

        table = document.add_table(rows=len(rows), cols=num_cols)
        table.style = "Table Grid"

        for row_idx, row_data in enumerate(rows):
            row = table.rows[row_idx]
            for col_idx in range(num_cols):
                cell = row.cells[col_idx]
                cell_text = row_data[col_idx] if col_idx < len(row_data) else ""
                # Supprimer les backticks et le formatage Markdown résiduel
                cell_text = re.sub(r"`([^`]+)`", r"\1", cell_text).strip()
                cell_text = re.sub(r"\*+", "", cell_text).strip()
                para = cell.paragraphs[0]
                run = para.add_run(cell_text)
                run.font.name = "Arial"
                run.font.size = Pt(10)

                if row_idx == 0:
                    run.bold = True
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                    self._set_cell_bg(cell, _HEADER_BG)
                elif row_idx % 2 == 0:
                    self._set_cell_bg(cell, _ALT_ROW_BG)

        document.add_paragraph()

    @staticmethod
    def _set_cell_bg(cell: Any, hex_color: str) -> None:
        """Applique une couleur de fond à une cellule Word."""
        tc_pr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_color)
        tc_pr.append(shd)

    # ------------------------------------------------------------------
    # Configuration du document
    # ------------------------------------------------------------------

    def _configure_page(self, document: Document, project_name: str = "Projet BI") -> None:
        from datetime import datetime
        section = document.sections[0]
        section.top_margin = Inches(1.1)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.1)
        section.right_margin = Inches(1.0)
        section.header_distance = Inches(0.4)
        section.footer_distance = Inches(0.3)
        section.different_first_page_header_footer = True

        # ── En-tête : titre projet à gauche + KEYRUS à droite (pages 2+) ──
        header = section.header
        header.is_linked_to_previous = False
        htable = header.add_table(rows=1, cols=2, width=Inches(6.5))
        htable.style = "Table Grid"
        # Supprimer les bordures du tableau d'en-tête
        for cell in htable.rows[0].cells:
            tc_pr = cell._tc.get_or_add_tcPr()
            tcBorders = OxmlElement("w:tcBorders")
            for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
                border = OxmlElement(f"w:{side}")
                border.set(qn("w:val"), "none")
                tcBorders.append(border)
            tc_pr.append(tcBorders)

        left_cell = htable.rows[0].cells[0]
        lp = left_cell.paragraphs[0]
        lr = lp.add_run(project_name)
        lr.font.name = "Arial"
        lr.font.size = Pt(9)
        lr.font.color.rgb = RGBColor(0, 48, 135)
        lr.bold = True

        right_cell = htable.rows[0].cells[1]
        rp = right_cell.paragraphs[0]
        rp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        rr = rp.add_run("Keyrus — Spécification Technique Détaillée")
        rr.font.name = "Arial"
        rr.font.size = Pt(9)
        rr.font.color.rgb = RGBColor(100, 100, 100)
        rr.italic = True

        # Ligne séparatrice sous l'en-tête
        hborder_para = header.add_paragraph()
        hborder_para.paragraph_format.space_before = Pt(2)
        hborder_para.paragraph_format.space_after = Pt(2)
        pPr = hborder_para._p.get_or_add_pPr()
        pBdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:space"), "1")
        bottom.set(qn("w:color"), _HEADER_BG)
        pBdr.append(bottom)
        pPr.append(pBdr)

        # ── Pied de page : Confidentiel à gauche, page X/N à droite ──
        footer = section.footer
        footer.is_linked_to_previous = False
        ftable = footer.add_table(rows=1, cols=3, width=Inches(6.5))
        ftable.style = "Table Grid"
        for cell in ftable.rows[0].cells:
            tc_pr = cell._tc.get_or_add_tcPr()
            tcBorders = OxmlElement("w:tcBorders")
            for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
                border = OxmlElement(f"w:{side}")
                border.set(qn("w:val"), "none")
                tcBorders.append(border)
            tc_pr.append(tcBorders)

        conf_cell = ftable.rows[0].cells[0]
        cp = conf_cell.paragraphs[0]
        cr = cp.add_run("🔒 Confidentiel — Keyrus")
        cr.font.name = "Arial"
        cr.font.size = Pt(8)
        cr.font.color.rgb = RGBColor(150, 0, 0)
        cr.italic = True

        date_cell = ftable.rows[0].cells[1]
        dp = date_cell.paragraphs[0]
        dp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        dr = dp.add_run(datetime.now().strftime("%d/%m/%Y"))
        dr.font.name = "Arial"
        dr.font.size = Pt(8)
        dr.font.color.rgb = RGBColor(120, 120, 120)

        page_cell = ftable.rows[0].cells[2]
        pp2 = page_cell.paragraphs[0]
        pp2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        self._add_page_number(pp2)

    @staticmethod
    def _add_page_number(paragraph: Any) -> None:
        """Insère un champ Word Page X / Total pages dans un paragraphe."""
        run = paragraph.add_run()
        run.font.name = "Arial"
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0, 48, 135)
        run.bold = True

        def _field(fld_type: str) -> None:
            fldChar = OxmlElement("w:fldChar")
            fldChar.set(qn("w:fldCharType"), fld_type)
            run._r.append(fldChar)

        def _instr(text: str) -> None:
            instrText = OxmlElement("w:instrText")
            instrText.set(qn("xml:space"), "preserve")
            instrText.text = text
            run._r.append(instrText)

        _field("begin"); _instr(" PAGE "); _field("separate"); _field("end")
        run2 = paragraph.add_run(" / ")
        run2.font.name = "Arial"
        run2.font.size = Pt(8)
        run2.font.color.rgb = RGBColor(0, 48, 135)
        run3 = paragraph.add_run()
        run3.font.name = "Arial"
        run3.font.size = Pt(8)
        run3.font.color.rgb = RGBColor(0, 48, 135)
        run3.bold = True

        def _field3(fld_type: str) -> None:
            fldChar = OxmlElement("w:fldChar")
            fldChar.set(qn("w:fldCharType"), fld_type)
            run3._r.append(fldChar)

        def _instr3(text: str) -> None:
            instrText = OxmlElement("w:instrText")
            instrText.set(qn("xml:space"), "preserve")
            instrText.text = text
            run3._r.append(instrText)

        _field3("begin"); _instr3(" NUMPAGES "); _field3("separate"); _field3("end")

    def _configure_fonts(self, document: Document) -> None:
        normal_style = document.styles["Normal"]
        normal_style.font.name = "Arial"
        normal_style.font.size = Pt(11)

        for style_name in ("Heading 1", "Heading 2", "Heading 3", "Heading 4"):
            if style_name in document.styles:
                style = document.styles[style_name]
                style.font.name = "Arial"
                level = int(style_name.split()[-1])
                style.font.size = Pt(max(11, 17 - level * 2))
                style.font.color.rgb = RGBColor(0, 48, 135)

    # ------------------------------------------------------------------
    # Méthode de compatibilité héritée
    # ------------------------------------------------------------------

    def assemble(
        self,
        dictionary_markdown: str,
        dat_markdown: str,
        diagram_path: str | Path,
        output_path: str | Path,
    ) -> Path:
        """Compatibilité avec l'ancien format (archivé)."""
        output_file = Path(output_path)
        document = Document()
        self._configure_page(document)
        self._configure_fonts(document)

        title_para = document.add_paragraph()
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title_para.add_run("Documentation Finale")
        run.bold = True
        run.font.name = "Arial"
        run.font.size = Pt(16)

        document.add_heading("Dictionnaire des données", level=1)
        self._render_markdown(document, dictionary_markdown)
        document.add_heading("Document d'Architecture Technique", level=1)
        self._render_markdown(document, dat_markdown)
        document.add_heading("Diagramme Mermaid", level=1)

        diagram_file = Path(diagram_path)
        if diagram_file.exists():
            document.add_picture(str(diagram_file), width=Inches(6.5))
        else:
            document.add_paragraph("Le fichier image du diagramme est introuvable.")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        saved_path = self._safe_save(document, output_file)
        LOGGER.info("Document Word généré: %s", saved_path)
        return saved_path
