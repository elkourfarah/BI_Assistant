"""Générateur de la section Sécurité et Gouvernance des Données (Action 4)."""
from __future__ import annotations

import logging
from typing import Any

from ...core.semantic_graph import StorageEngine, UnifiedSemanticGraph

LOGGER = logging.getLogger(__name__)


def generate_security_chapter(graph: UnifiedSemanticGraph, context: dict[str, Any]) -> str:
    """Génère les recommandations de sécurité et gouvernance adaptées aux moteurs réels."""
    engines = graph.storage_engines
    has_sql = StorageEngine.SQL in engines or graph.has_sql
    has_pbix = StorageEngine.POWERBI in engines or graph.has_pbix
    has_excel = StorageEngine.EXCEL in engines or graph.has_excel

    lines: list[str] = [
        f"*Cette section formalise la politique de sécurité, la gestion des habilitations d'accès "
        f"et la gouvernance des données appliquées au projet **{graph.project_name}**.*",
        "",
    ]

    # 1. Sécurité SQL & Base de données
    if has_sql:
        lines.extend([
            "### 1. Sécurité de la Couche Base de Données & ETL (SQL)",
            "- **Contrôle d'accès basé sur les rôles (RBAC)** :",
            "  - Comptes de service dédiés et nominatifs pour l'exécution des flux ETL (`ETL_USER`), restreints en écriture aux seules tables cibles du schéma DWH.",
            "  - Accès en lecture seule (`READ_ONLY_ROLE`) pour les utilisateurs et outils de restitution décisionnelle.",
            "  - Principe du moindre privilège appliqué sur les tables de Staging (accès interdit aux profils métier finaux).",
            "- **Chiffrement au repos (TDE)** : Activation du chiffrement transparent des données (*Transparent Data Encryption*) sur les tablespaces et fichiers de bases de données.",
            "- **Chiffrement en transit** : Connexions réseau chiffrées via TLS 1.3 / SSL obligatoire pour tous les flux inter-systèmes et pilotes ODBC/JDBC.",
            "- **Journalisation & Audit** : Traçabilité systématique des requêtes DDL et des accès aux tables sensibles dans les journaux d'audit.",
            "",
        ])

    # 2. Sécurité Power BI & Modèle Sémantique
    if has_pbix:
        lines.extend([
            "### 2. Sécurité du Modèle Sémantique & Restitution (Power BI)",
            "- **Sécurité au niveau des lignes (Row-Level Security - RLS)** :",
            "  - Définition de rôles de sécurité dynamiques basés sur les fonctions DAX `USERPRINCIPALNAME()` ou `USERNAME()` pour restreindre la visibilité des données selon le périmètre géographique, organisationnel ou hiérarchique de l'utilisateur.",
            "  - Validation des rôles dans Power BI Desktop via la fonctionnalité *Afficher comme rôle* avant déploiement.",
            "- **Gestion des espaces de travail (Workspaces)** :",
            "  - Séparation stricte des rôles : Administrateur, Membre, Contributeur et Lecteur (*Viewer*). Seuls les développeurs habilités disposent du droit d'écriture.",
            "  - Publication des rapports finaux au travers d'une Application Power BI dédiée avec contrôle d'accès par groupes de sécurité Microsoft Entra ID (Azure AD).",
            "- **Protection des informations & Prévention des fuites** :",
            "  - Application des étiquettes de confidentialité Microsoft Purview (ex: *Interne*, *Confidentiel*).",
            "  - Désactivation de l'export de données sous-jacentes non agrégées pour les profils non autorisés.",
            "",
        ])

    # 3. Sécurité des Fichiers Tabulaires & Référentiels
    if has_excel:
        lines.extend([
            "### 3. Sécurité des Fichiers de Paramétrage & Référentiels (Excel / CSV)",
            "- **Contrôle d'accès au stockage (ACLs)** : Restriction d'accès aux répertoires réseau, partages SharePoint ou conteneurs Lakehouse hébergeant les fichiers sources aux seuls administrateurs de données autorisés.",
            "- **Intégrité et immutabilité** : Protection des feuilles de calcul et classeurs de paramètres contre les modifications accidentelles de structure (colonnes, types).",
            "- **Masquage et anonymisation** : Élimination préventive ou hachage (SHA-256) de toute donnée personnelle directement identifiable (PII) avant ingestion dans les pipelines.",
            "",
        ])

    # 4. Gouvernance globale et conformité
    lines.extend([
        "### 4. Conformité & Gouvernance Globale",
        "- **Conformité RGPD / GDPR** : Respect des règles de minimisation des données collectées et purge programmée des tables techniques au-delà de la durée légale de conservation.",
        "- **Rétention des données** : Les tables de Staging sont purgées après validation du chargement DWH (politique de rétention glissante recommandée de 30 jours pour le diagnostic).",
        "- **Gestion des secrets** : Stockage des identifiants et chaînes de connexion dans un coffre-fort sécurisé (Azure Key Vault, CyberArk ou variables d'environnement chiffrées), interdisant tout mot de passe en clair dans les scripts.",
    ])

    return "\n".join(lines)
