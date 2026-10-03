# 🚀 Assistant BI Keyrus — Générateur Automatique de Spécifications Techniques Détaillées (STD)

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-18%2F18%20passed-brightgreen.svg)]()
[![LLM Powered](https://img.shields.io/badge/LLM-Groq%20API-orange.svg)](https://groq.com/)
[![Output Format](https://img.shields.io/badge/output-Word%20(.docx)-003087.svg)]()

> **Solution d'ingénierie BI & IA pour automatiser la rédaction de Spécifications Techniques Détaillées (STD) à partir de modèles Power BI (`.pbix`), de scripts SQL (ETL/DWH) et de référentiels Excel/CSV.**

---

## 📋 Présentation du Projet

Dans le cadre des projets de Business Intelligence et de Data Engineering chez **Keyrus**, la rédaction de la documentation technique (Spécifications Techniques Détaillées - STD) d'un projet décisionnel est une tâche critique mais chronophage (généralement 2 à 3 jours ouvrés pour un consultant ou data architecte).

**L'Assistant BI Keyrus** réduit ce cycle de **3 jours à moins de 60 secondes** :
- **Extraction automatique** des modèles tabulaires Power BI (`.pbix`), scripts SQL (DDL/DML/ETL) et classeurs Excel.
- **Parser AST SQL multi-dialectes** (Oracle, Snowflake, T-SQL, Spark, Postgres via `sqlglot`).
- **Génération assistée par LLM** (Groq) pour l'enrichissement sémantique des colonnes, règles de gestion et glossaire métier.
- **Bouclier anti-hallucination** : strict respect des schémas réels (aucune table ni métrique inventée).
- **Livrable Word client** (`.docx`) prêt à l'emploi respectant la charte graphique et typographique de Keyrus.

---

## 🏗️ Architecture du Pipeline (7 Couches)

```
[ Fichiers Entrées ] ───▶ (1. Input Processor & Décompression ZIP/RAR)
                                   │
                                   ▼
                       (2. Extracteurs Spécialisés)
                        ├── PBIX Extractor (pbixray)
                        ├── SQL Extractor (AST sqlglot)
                        └── Excel Extractor (pandas/openpyxl)
                                   │
                                   ▼
                       (3. RAG & Template Store)
                                   │
                                   ▼
                       (4. Moteur Hybride & LLM Groq)
                        ├── Enrichissement sémantique
                        └── Chaîne de Fallback & Retries
                                   │
                                   ▼
                       (5. Constructeur Documentaire)
                                   │
                                   ▼
                       [ Document Word STD Final (.docx) ]
```

---

## ⚙️ Prérequis

- **Python 3.10 ou supérieur**
- Une clé d'API **Groq** valide (gratuite sur [console.groq.com](https://console.groq.com/keys))
- Git

---

## 🚀 Installation Rapide

### 1. Cloner le dépôt
```bash
git clone <URL_DU_DEPOT_GIT>
cd Assistant_BI_Keyrus
```

### 2. Créer et activer l'environnement virtuel

**Sur Windows (PowerShell) :**
```powershell
python -m venv venv
.\venv\Scripts\activate
```

**Sur Linux / macOS :**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Installer les dépendances
```bash
pip install -r requirements.txt
```

### 4. Configurer les variables d'environnement
Créez un fichier `.env` à la racine à partir du modèle fourni :

```bash
cp .env.example .env
```

Éditez le fichier `.env` pour y renseigner votre clé API :
```ini
GROQ_API_KEY=gsk_votre_cle_groq_secrete_ici
GROQ_MODEL=openai/gpt-oss-20b
```

---

## 💻 Utilisation & Commandes CLI

Le point d'entrée principal est le fichier `main.py`.

### Exemples d'exécution :

1. **Analyser un rapport Power BI (`.pbix`) :**
```powershell
python main.py --pbix samples/pbix/Supplier-Quality-Analysis-Sample-PBIX.pbix --project "Supplier Quality Analysis"
```

2. **Analyser des scripts SQL (Data Warehouse / ETL) :**
```powershell
python main.py --sql samples/sql/ --dialect oracle --project "DWH Keyrus CRM"
```

3. **Analyser des fichiers Excel de mapping et référentiels :**
```powershell
python main.py --excel samples/csv/params_config.csv --project "Cartographie Paramètres"
```

4. **Traitement complet via archive ZIP (détection automatique) :**
```powershell
python main.py --zip paquet_client.zip --output output/
```

5. **Traitement multi-sources combiné :**
```powershell
python main.py --pbix samples/pbix/ --sql samples/sql/ --project "Projet Global BI"
```

Les documents Word générés sont automatiquement déposés dans le dossier `output/` (ex : `output/Documentation_Finale.docx`).

---

## 🧪 Tests & Validation

Le projet intègre une suite de tests unitaires couvrant l'ensemble des modules d'extraction, du RAG et du générateur documentaire.

Pour lancer les tests :
```powershell
python run_tests.py
```
*Ou avec pytest :*
```powershell
pytest tests/ -v
```

> **Résultat :** `18 / 18 tests passing (100%)`

---

## 📂 Structure du Projet

```text
Assistant_BI_Keyrus/
├── .env.example            # Gabarit de configuration des variables d'environnement
├── .gitignore              # Exclusion des secrets, venvs et caches
├── README.md               # Documentation complète du projet
├── requirements.txt        # Dépendances Python requises
├── main.py                 # Point d'entrée CLI du pipeline
├── run_tests.py            # Script d'exécution rapide de la suite de tests
│
├── config/                 # Configurations additionnelles
├── samples/                # Échantillons de test
│   ├── pbix/               # Rapports Power BI d'exemple
│   ├── sql/                # Scripts SQL DWH / ETL
│   └── csv/                # Mappings & référentiels CSV
│
├── src/                    # Code source principal
│   ├── builders/           # Assemblage des documents Word (python-docx)
│   ├── composer/           # Génération des sections (glossaire, architecture, etc.)
│   ├── extractors/         # Moteurs d'extraction PBIX, SQL (sqlglot), Excel
│   ├── llm/                # Client Groq, gestion des quotas et fallback
│   ├── models/             # Modèles de données (Tables, Colonnes, Métriques)
│   ├── rag/                # Indexation et templates de sections STD
│   ├── reasoning/          # Moteur d'inférence et bouclier anti-hallucination
│   └── sections/           # Définition des métadonnées et chapitres
│
├── tests/                  # Tests unitaires du pipeline
└── output/                 # Dossier de génération des documents Word
```

---

## 🔐 Bonnes Pratiques & Sécurité

- **Ne committez jamais le fichier `.env`** contenant vos clés d'API. Le fichier est strictement ignoré par le `.gitignore`.
- Seul `.env.example` doit être versionné.

---

## 👤 Auteur

- **Farah Elkour** — Data & BI Consultant / Ingénieur Data Keyrus & ESPRIT
