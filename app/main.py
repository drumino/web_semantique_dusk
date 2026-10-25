"""API FastAPI : traçabilité sémantique des déchets (SPARQL + NLP)."""
import os
import re
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .inference import run_inference
from .nlp import NLQ
from .store import Store, lots_query

BASE = os.path.dirname(__file__)
STATIC = os.path.join(BASE, "..", "static")

app = FastAPI(title="Traçabilité sémantique des déchets", version="1.0")
store = Store()
nlq = NLQ(store)


class LotIn(BaseModel):
    producteur: str
    dechet: str
    transporteur: str
    centre: str
    procede: str
    poids: float = Field(gt=0)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    matiere: Optional[str] = None


class LotUpdate(BaseModel):
    poids: Optional[float] = Field(default=None, gt=0)
    centre: Optional[str] = None
    procede: Optional[str] = None
    transporteur: Optional[str] = None


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=300)


class RawQuery(BaseModel):
    query: str


def result(q, cols, rows):
    return {"sparql": q, "colonnes": cols, "lignes": rows}


@app.get("/api/refs")
def refs():
    return store.refs()


@app.get("/api/lots")
def list_lots(search: Optional[str] = None, producteur: Optional[str] = None,
              centre: Optional[str] = None, min_poids: Optional[float] = None,
              valorise: Optional[bool] = None, dangereux: bool = False,
              non_conforme: bool = False):
    f = {"search": search, "producteur": producteur, "centre": centre, "min_poids": min_poids,
         "valorise": valorise, "non_conforme": non_conforme,
         "dechet_class": ["DechetDangereux"] if dangereux else None}
    try:
        q = lots_query({k: v for k, v in f.items() if v not in (None, "")})
        return result(q, *store.select(q))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/lots/{lot_id}")
def trace_lot(lot_id: str):
    try:
        q = lots_query({"lot": lot_id}, mode="trace")
    except ValueError as e:
        raise HTTPException(400, str(e))
    cols, rows = store.select(q)
    if not rows:
        raise HTTPException(404, "Lot introuvable")
    return {**result(q, cols, rows), "lot": rows[0]}


@app.post("/api/lots", status_code=201)
def create_lot(lot: LotIn):
    try:
        lid, q = store.create_lot(lot.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    nlq.refresh()
    return {"id": lid, "sparql": q}


@app.put("/api/lots/{lot_id}")
def update_lot(lot_id: str, body: LotUpdate):
    try:
        return {"id": lot_id, "sparql": store.update_lot(lot_id, body.model_dump(exclude_none=True))}
    except KeyError:
        raise HTTPException(404, "Lot introuvable")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/lots/{lot_id}")
def delete_lot(lot_id: str):
    try:
        return {"id": lot_id, "sparql": store.delete_lot(lot_id)}
    except KeyError:
        raise HTTPException(404, "Lot introuvable")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/stats")
def stats():
    def one(q):
        return store.select(q)[1][0]["total"] or 0
    total_poids = one(lots_query(mode="sum"))
    valorise = one(lots_query({"valorise": True}, mode="sum"))
    return {
        "lots": one(lots_query(mode="count")),
        "poids_total": total_poids,
        "poids_valorise": valorise,
        "taux_valorisation": round(100 * valorise / total_poids, 1) if total_poids else 0,
        "lots_dangereux": one(lots_query({"dechet_class": ["DechetDangereux"]}, mode="count")),
        "lots_non_conformes": one(lots_query({"non_conforme": True}, mode="count")),
        "poids_par_procede": store.select(lots_query(mode="sum", group_by="procede"))[1],
        "poids_par_producteur": store.select(lots_query(mode="sum", group_by="producteur"))[1],
    }


@app.get("/api/inference")
def inference():
    return run_inference(store)


@app.get("/api/validate")
def validate_all():
    """Validation SHACL de toute la base : liste des violations."""
    v = store.validate_all()
    return {"conforme": not v, "violations": v}


@app.get("/api/graph")
def graph():
    """Graphe de traçabilité (noeuds/arêtes) pour la visualisation."""
    _, rows = store.select(lots_query(mode="trace"))
    danger = {r["lot"] for r in store.select(lots_query({"dechet_class": ["DechetDangereux"]}))[1]}
    nodes, edges = {}, []

    def node(kind, label, **extra):
        nodes.setdefault(f"{kind}:{label}", {"id": f"{kind}:{label}", "kind": kind, "label": label, **extra})
        return f"{kind}:{label}"

    for r in rows:
        lot = node("lot", r["nom"], dangereux=r["lot"] in danger, id_lot=r["lot"],
                   non_conforme=r["lot"] in danger and r["agree"] is False)
        edges.append([node("producteur", r["producteur"]), lot])
        edges.append([node("transporteur", r["transporteur"]), lot])
        edges.append([lot, node("centre", r["centre"], non_agree=r["agree"] is False)])
        edges.append([lot, node("procede", r["procede"])])
        if r.get("matiere"):
            edges.append([lot, node("matiere", r["matiere"])])
    return {"nodes": list(nodes.values()), "edges": edges}


@app.post("/api/nlq")
def natural_language(body: Question):
    return nlq.ask(body.question)


FORBIDDEN = re.compile(r"\b(insert|delete|drop|clear|load|create|add|move|copy|service)\b", re.I)


@app.post("/api/sparql")
def raw_sparql(body: RawQuery):
    """Console SPARQL en lecture seule (SELECT / ASK)."""
    q = body.query.strip()
    core = re.sub(r'"[^"]*"', "", re.sub(r"(?im)^\s*(PREFIX|BASE)\b.*$", "", q))
    kind = re.search(r"\b(select|ask)\b", core, re.I)
    if FORBIDDEN.search(core) or not kind:
        raise HTTPException(400, "Seules les requêtes de lecture (SELECT/ASK) sont autorisées ici.")
    try:
        if kind.group(1).lower() == "ask":
            return {"ask": store.ask(q)}
        cols, rows = store.select(q)
    except Exception as e:
        raise HTTPException(400, f"Requête invalide : {e}")
    return result(q, cols, rows)


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC), name="static")
