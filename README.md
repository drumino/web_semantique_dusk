# EcoTrace – Traçabilité sémantique des déchets (mini-projet Web Sémantique)

Ontologie OWL (Owlready2) + triplestore rdflib + API FastAPI + interface web + module NLP (spaCy) qui traduit
une question en français en requête SPARQL. Aucun LLM / API externe.

## Installation
```bash
python -m venv .venv && source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements.txt
python -m spacy download fr_core_news_sm                # modèle français (lemmes) – optionnel, repli automatique sinon
python ontologie_dechets.py                             # génère dechets.owl (+ raisonnement HermiT si Java installé)
cp dechets.owl data/dechets.owl                         # Windows : copy dechets.owl data\dechets.owl
uvicorn app.main:app --reload
```
Ouvrir http://127.0.0.1:8000 (documentation de l'API : http://127.0.0.1:8000/docs).
Java (JRE) est nécessaire uniquement pour HermiT ; sans Java, le bouton « raisonneur » utilise des règles SPARQL équivalentes.

## Tests
`python tests/test_app.py` (utilise une copie temporaire de l'ontologie).

## Structure
| Fichier | Rôle |
|---|---|
| `ontologie_dechets.py` | Classes, propriétés, axiomes, individus ; export RDF/XML ; HermiT |
| `app/store.py` | rdflib : requêtes SPARQL paramétrées (filtres, agrégats) et CRUD (INSERT DATA, DELETE/INSERT, DELETE WHERE) |
| `app/nlp.py` | NLP : spaCy + rapidfuzz → intention, entités, contraintes → SPARQL |
| `app/inference.py` | Raisonnement HermiT (Owlready2) |
| `app/validation.py` + `data/shapes.ttl` | Validation SHACL (pyshacl) : contraintes structurelles + règle « déchet dangereux ⇒ centre agréé » |
| `app/main.py` | API REST + service du front |
| `static/index.html` | Interface (tableau de bord, lots, question en langage naturel, console SPARQL) |

## API
`GET /api/stats` · `GET /api/refs` · `GET|POST /api/lots` · `GET|PUT|DELETE /api/lots/{id}` ·
`GET /api/inference` · `GET /api/validate` (SHACL) · `GET /api/graph` · `POST /api/nlq {"question": "..."}` · `POST /api/sparql {"query": "..."}` (lecture seule)

## Pipeline NLP (à présenter)
1. Normalisation (minuscules, sans accents) et tokenisation **spaCy** (+ lemmes avec `fr_core_news_sm`).
2. **Liaison d'entités** : lexique construit automatiquement depuis l'ontologie (noms d'individus, villes),
   `PhraseMatcher` spaCy pour les correspondances exactes, **rapidfuzz** pour les fautes de frappe.
3. **Détection d'intention** par règles linguistiques : lister, compter, somme, tracer un lot, relation d'un lot, matière issue d'un déchet.
4. **Extraction de contraintes** : seuils de poids (kg/tonnes), dates (« après le 2026-10-01 », mois), classes (dangereux, plastique…), états (valorisé, non conforme).
5. **Génération SPARQL** par gabarits paramétrés (identifiants validés, littéraux échappés), partagés avec l'API REST.

Exemples : « Lots de plus de 500 kg produits par PlastiPack », « Combien de lots ont été recyclés ? »,
« Quels centres ne sont pas agréés ? », « Parcours du lot 7 », « Poids total valorisé par procédé ».

## Valeur ajoutée
- **HermiT** : classes inférées `LotDangereux`, `LotValorise`, `LotNonConforme`, `CentreNonAgree`.
- **SHACL** : toute création ou modification de lot est validée sur une copie du graphe ; en cas de violation, rien n'est écrit
  (HTTP 400 avec le message). `GET /api/validate` audite toute la base (le lot L08 est volontairement non conforme).
- **Graphe interactif** de traçabilité (onglet « Graphe »).

## Scénario de démonstration (5 min)
1. Tableau de bord : 12 lots, 80,4 % de valorisation, 1 lot non conforme ; lancer SHACL puis le raisonneur.
2. Onglet Lots : tracer le lot L02 (bouteilles PET → recyclage → granules PET) ; modifier son poids.
3. « Poser une question » : « Quels centres ne sont pas agréés ? », « Lots de plus de 500 kg produits par PlastiPack », « Parcours du lot 7 » ; montrer la requête SPARQL générée.
4. Créer un lot de solvants usagés traité par DecharteBizerte : refus SHACL.
5. Onglet Graphe : cliquer sur Lot L08 (en rouge).
