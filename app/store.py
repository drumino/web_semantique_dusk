"""Accès au triplestore (rdflib) : requêtes SPARQL, construction de filtres, CRUD."""
import datetime
import os
import re
import threading
from decimal import Decimal

from rdflib import Graph

from .validation import violations

NS = "http://esprit.tn/dechets.owl#"
PREFIXES = f"""PREFIX d: <{NS}>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""
DATA_FILE = os.environ.get(
    "DECHETS_FILE",
    os.path.join(os.path.dirname(__file__), "..", "data", "dechets.owl"),
)

ID_RE = re.compile(r"^[A-Za-z0-9_]+$")
GROUPS = {"producteur": "?producteur", "dechet": "?dechet", "transporteur": "?transporteur",
          "centre": "?centre", "procede": "?procede"}


def safe_id(value: str) -> str:
    """Valide un identifiant avant de l'insérer dans une requête (anti-injection SPARQL)."""
    if not isinstance(value, str) or not ID_RE.match(value):
        raise ValueError(f"Identifiant invalide : {value!r}")
    return value


def esc(text: str) -> str:
    """Échappe une chaîne pour un littéral SPARQL."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def cell(v):
    """Convertit une valeur rdflib en valeur JSON lisible."""
    if v is None:
        return None
    if hasattr(v, "toPython"):
        p = v.toPython()
        if isinstance(p, Decimal):
            return float(p)
        if isinstance(p, datetime.datetime):
            return p.date().isoformat() if p.time() == datetime.time(0) else p.isoformat()
        if isinstance(p, (bool, int, float)):
            return p
        s = str(p)
        return s.split("#")[-1] if s.startswith(NS) else s
    return str(v)


# ---------------------------------------------------------------------------
# Construction des requêtes sur les lots (utilisée par l'API REST ET par le NLP)
# ---------------------------------------------------------------------------
LOT_BASE = """
  ?lot a d:Lot ; d:nom ?nom ; d:poidsKg ?poids ; d:dateProduction ?date ;
       d:produitPar ?prd ; d:contientDechet ?dec ; d:transportePar ?trs ;
       d:traitePar ?cen ; d:subitProcede ?prc .
  ?prd d:nom ?producteur . ?dec d:nom ?dechet . ?trs d:nom ?transporteur .
  ?cen d:nom ?centre . ?prc d:nom ?procede .
"""
VALORISANT = "?prc rdf:type/rdfs:subClassOf* d:ProcedeValorisant ."


def lots_query(f: dict | None = None, mode: str = "list", group_by: str | None = None) -> str:
    """Construit la requête SPARQL sur les lots à partir d'un dictionnaire de filtres.

    mode : list | count | sum | trace.   group_by : producteur | dechet | ... (mode sum)
    """
    f = f or {}
    pat, flt = [LOT_BASE], []

    if f.get("lot"):
        flt.append(f"?lot = d:{safe_id(f['lot'])}")
    if f.get("search"):
        s = esc(f["search"])
        flt.append(" || ".join(f'CONTAINS(LCASE(STR(?{v})), LCASE("{s}"))' for v in
                               ("nom", "producteur", "dechet", "centre", "transporteur")))
    if f.get("min_poids") is not None:
        flt.append(f"?poids > {float(f['min_poids'])}")
    if f.get("max_poids") is not None:
        flt.append(f"?poids < {float(f['max_poids'])}")
    for key, var in (("producteur", "?prd"), ("transporteur", "?trs"), ("centre", "?cen"),
                     ("dechet", "?dec"), ("procede", "?prc")):
        if f.get(key):
            flt.append(f"{var} = d:{safe_id(f[key])}")
    if f.get("matiere"):
        pat.append(f"?lot d:produitMatiere d:{safe_id(f['matiere'])} .")
    if f.get("ville"):
        pat.append("?prd d:localiseA ?sp . ?sp d:ville ?vp .")
        flt.append(f'LCASE(STR(?vp)) = LCASE("{esc(f["ville"])}")')

    classes = list(f.get("dechet_class") or [])
    if f.get("non_conforme") and "DechetDangereux" not in classes:
        classes.append("DechetDangereux")
    for c in classes:
        pat.append(f"?dec rdf:type/rdfs:subClassOf* d:{safe_id(c)} .")
    if f.get("non_conforme"):
        pat.append("?cen d:estAgree ?agree .")
        flt.append("?agree = false")

    if f.get("valorise") is True:
        pat.append(VALORISANT)
    elif f.get("valorise") is False:
        flt.append(f"NOT EXISTS {{ {VALORISANT} }}")

    if f.get("after"):
        flt.append(f'?date >= "{esc(f["after"])}T00:00:00"^^xsd:dateTime')
    if f.get("before"):
        flt.append(f'?date < "{esc(f["before"])}T00:00:00"^^xsd:dateTime')
    if f.get("month"):
        flt.append(f"MONTH(?date) = {int(f['month'])}")
    if f.get("year"):
        flt.append(f"YEAR(?date) = {int(f['year'])}")

    if mode == "trace":
        pat.append("OPTIONAL { ?lot d:produitMatiere ?m . ?m d:nom ?matiere }")
        pat.append("OPTIONAL { ?cen d:estAgree ?agree }")
        pat.append("OPTIONAL { ?lot d:numeroBordereau ?bordereau }")
    where = "\n".join(pat) + "".join(f"\n  FILTER({x})" for x in flt)

    if mode == "count":
        return f"SELECT (COUNT(DISTINCT ?lot) AS ?total)\nWHERE {{{where}\n}}"
    if mode == "sum":
        if group_by in GROUPS:
            g = GROUPS[group_by]
            return (f"SELECT {g} (SUM(?poids) AS ?total)\nWHERE {{{where}\n}}\n"
                    f"GROUP BY {g}\nORDER BY DESC(?total)")
        return f"SELECT (SUM(?poids) AS ?total)\nWHERE {{{where}\n}}"
    if mode == "trace":
        return ("SELECT ?lot ?nom ?bordereau ?poids ?date ?producteur ?dechet ?transporteur ?centre "
                f"?agree ?procede ?matiere\nWHERE {{{where}\n}}")
    return ("SELECT DISTINCT ?lot ?nom ?poids ?date ?producteur ?dechet ?transporteur ?centre ?procede\n"
            f"WHERE {{{where}\n}}\nORDER BY ?lot")


def class_query(cls: str, agree: bool | None = None, count: bool = False) -> str:
    """Instances d'une classe (sous-classes incluses), éventuellement filtrées sur estAgree."""
    extra = ""
    if agree is not None:
        extra = f"?x d:estAgree ?ag . FILTER(?ag = {'true' if agree else 'false'})"
    body = f"?x rdf:type/rdfs:subClassOf* d:{safe_id(cls)} ; d:nom ?nom . {extra}"
    if count:
        return f"SELECT (COUNT(DISTINCT ?x) AS ?total)\nWHERE {{ {body} }}"
    return f"SELECT DISTINCT ?x ?nom\nWHERE {{ {body} }}\nORDER BY ?nom"


class Store:
    def __init__(self, path: str = DATA_FILE):
        self.path = os.path.abspath(path)
        self.lock = threading.RLock()
        self.g = Graph()
        self.g.parse(self.path, format="xml")

    # -- lecture / écriture ------------------------------------------------
    def select(self, q: str):
        with self.lock:
            res = self.g.query(PREFIXES + q)
            cols = [str(v) for v in res.vars]
            rows = [{c: cell(r[i]) for i, c in enumerate(cols)} for r in res]
        return cols, rows

    def ask(self, q: str) -> bool:
        with self.lock:
            return bool(self.g.query(PREFIXES + q).askAnswer)

    def update(self, *ops: str) -> str:
        """Exécute une ou plusieurs opérations SPARQL Update (préfixes déclarés devant chacune)."""
        with self.lock:
            self.g.update(";\n".join(PREFIXES + op for op in ops))
            self.g.serialize(destination=self.path, format="xml")
        return ";\n".join(ops)

    def check(self, ops: list[str], focus: str):
        """Applique les opérations sur une copie du graphe et valide le lot visé avec SHACL."""
        with self.lock:
            tmp = Graph()
            tmp += self.g
            tmp.update(";\n".join(PREFIXES + op for op in ops))
        found = violations(tmp, focus)
        if found:
            raise ValueError("Validation SHACL : " + " ; ".join(v["message"] for v in found))

    def validate_all(self) -> list[dict]:
        with self.lock:
            return violations(self.g)

    # -- références pour les formulaires ------------------------------------
    def refs(self) -> dict:
        kinds = {"producteurs": "Producteur", "transporteurs": "Transporteur",
                 "centres": "CentreTraitement", "dechets": "Dechet",
                 "procedes": "ProcedeTraitement", "matieres": "MatiereSecondaire"}
        out = {}
        for key, cls in kinds.items():
            _, rows = self.select(class_query(cls))
            out[key] = [{"id": r["x"], "nom": r["nom"]} for r in rows]
        return out

    def kind_ok(self, ident: str, cls: str) -> bool:
        return self.ask(f"ASK {{ d:{safe_id(ident)} rdf:type/rdfs:subClassOf* d:{cls} }}")

    # -- CRUD sur les lots ---------------------------------------------------
    def next_lot_id(self) -> str:
        _, rows = self.select("SELECT ?lot WHERE { ?lot a d:Lot }")
        nums = [int(m.group(1)) for r in rows if (m := re.match(r"Lot_L(\d+)$", r["lot"]))]
        return f"Lot_L{(max(nums) + 1 if nums else 1):02d}"

    def create_lot(self, data: dict):
        # Keep ID allocation, SHACL validation, and persistence in one critical section.
        # Otherwise concurrent requests could allocate the same next ID or validate
        # against a graph that changes before the INSERT is written.
        with self.lock:
            return self._create_lot(data)

    def _create_lot(self, data: dict):
        checks = [("producteur", "Producteur"), ("dechet", "Dechet"), ("transporteur", "Transporteur"),
                  ("centre", "CentreTraitement"), ("procede", "ProcedeTraitement")]
        for key, cls in checks:
            if not self.kind_ok(data[key], cls):
                raise ValueError(f"{key} inconnu : {data[key]}")
        if data.get("matiere") and not self.kind_ok(data["matiere"], "MatiereSecondaire"):
            raise ValueError(f"matiere inconnue : {data['matiere']}")
        day = datetime.date.fromisoformat(data["date"])
        lid = self.next_lot_id()
        num = lid.split("L")[-1]
        triples = [
            f'd:{lid} a owl:NamedIndividual, d:Lot', f'd:nom "Lot L{num}"',
            f'd:numeroBordereau "BSD-{day.year}-{num.zfill(3)}"',
            f'd:poidsKg "{float(data["poids"])}"^^xsd:decimal',
            f'd:dateProduction "{day.isoformat()}T00:00:00"^^xsd:dateTime',
            f'd:produitPar d:{data["producteur"]}', f'd:contientDechet d:{data["dechet"]}',
            f'd:transportePar d:{data["transporteur"]}', f'd:traitePar d:{data["centre"]}',
            f'd:subitProcede d:{data["procede"]}',
        ]
        if data.get("matiere"):
            triples.append(f'd:produitMatiere d:{data["matiere"]}')
        q = "INSERT DATA {\n  " + " ;\n  ".join(triples) + " .\n}"
        self.check([q], lid)
        self.update(q)
        return lid, q

    def lot_exists(self, lid: str) -> bool:
        return self.ask(f"ASK {{ d:{safe_id(lid)} a d:Lot }}")

    def update_lot(self, lid: str, data: dict) -> str:
        with self.lock:
            return self._update_lot(lid, data)

    def _update_lot(self, lid: str, data: dict) -> str:
        if not self.lot_exists(lid):
            raise KeyError(lid)
        ops = []
        if data.get("poids") is not None:
            ops.append(f'DELETE {{ d:{lid} d:poidsKg ?o }}\nINSERT {{ d:{lid} d:poidsKg '
                       f'"{float(data["poids"])}"^^xsd:decimal }}\nWHERE {{ OPTIONAL {{ d:{lid} d:poidsKg ?o }} }}')
        for key, prop, cls in (("centre", "traitePar", "CentreTraitement"),
                               ("procede", "subitProcede", "ProcedeTraitement"),
                               ("transporteur", "transportePar", "Transporteur")):
            if data.get(key):
                if not self.kind_ok(data[key], cls):
                    raise ValueError(f"{key} inconnu : {data[key]}")
                ops.append(f'DELETE {{ d:{lid} d:{prop} ?o }}\nINSERT {{ d:{lid} d:{prop} d:{data[key]} }}\n'
                           f'WHERE {{ OPTIONAL {{ d:{lid} d:{prop} ?o }} }}')
        if not ops:
            raise ValueError("Aucun champ à modifier")
        self.check(ops, lid)
        return self.update(*ops)

    def delete_lot(self, lid: str) -> str:
        with self.lock:
            return self._delete_lot(lid)

    def _delete_lot(self, lid: str) -> str:
        if not self.lot_exists(safe_id(lid)):
            raise KeyError(lid)
        return self.update(f"DELETE WHERE {{ d:{lid} ?p ?o }}", f"DELETE WHERE {{ ?s ?p d:{lid} }}")
