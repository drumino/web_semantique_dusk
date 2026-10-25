"""Tests de bout en bout : python -m pytest tests -q   (ou python tests/test_app.py)"""
import os, shutil, sys, tempfile

HERE = os.path.dirname(__file__)
tmp = os.path.join(tempfile.mkdtemp(), "dechets.owl")
shutil.copy(os.path.join(HERE, "..", "data", "dechets.owl"), tmp)
os.environ["DECHETS_FILE"] = tmp
sys.path.insert(0, os.path.join(HERE, ".."))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)


def test_stats_and_refs():
    s = c.get("/api/stats").json()
    assert s["lots"] == 12 and s["lots_non_conformes"] == 1
    assert len(c.get("/api/refs").json()["producteurs"]) == 5


def test_filters_and_trace():
    r = c.get("/api/lots", params={"min_poids": 800, "valorise": True}).json()
    assert {x["lot"] for x in r["lignes"]} == {"Lot_L01", "Lot_L07"}
    assert c.get("/api/lots/Lot_L08").json()["lot"]["agree"] is False
    assert c.get("/api/lots/Lot_L99").status_code == 404
    assert c.get("/api/lots/Lot_L01%22%20x").status_code in (400, 404, 422)


def test_crud():
    body = dict(producteur="PlastiPack", dechet="Bouteilles_PET", transporteur="LogiVert",
                centre="RecyTunis", procede="P_Recyclage", poids=555, date="2026-10-20")
    r = c.post("/api/lots", json=body)
    assert r.status_code == 201, r.text
    lid = r.json()["id"]
    assert c.put(f"/api/lots/{lid}", json={"poids": 999, "centre": "EcoCompost"}).status_code == 200
    assert c.get(f"/api/lots/{lid}").json()["lot"]["poids"] == 999.0
    assert c.get(f"/api/lots/{lid}").json()["lot"]["centre"] == "EcoCompost"
    assert c.post("/api/lots", json={**body, "centre": "Inconnu"}).status_code == 400
    assert c.delete(f"/api/lots/{lid}").status_code == 200
    assert c.get(f"/api/lots/{lid}").status_code == 404
    assert c.get("/api/stats").json()["lots"] == 12


def test_shacl_and_graph():
    v = c.get("/api/validate").json()
    assert not v["conforme"] and {x["lot"] for x in v["violations"]} == {"Lot_L08"}
    bad = dict(producteur="ChimieSud", dechet="Solvants_Usages", transporteur="CamionPlus",
               centre="DecharteBizerte", procede="P_Enfouissement", poids=100, date="2026-10-21")
    r = c.post("/api/lots", json=bad)
    assert r.status_code == 400 and "SHACL" in r.json()["detail"], r.text
    assert c.get("/api/stats").json()["lots"] == 12          # rien n'a été écrit
    ok = c.put("/api/lots/Lot_L04", json={"centre": "DecharteBizerte"})
    assert ok.status_code == 400
    g = c.get("/api/graph").json()
    assert len(g["nodes"]) > 30 and any(n.get("non_conforme") for n in g["nodes"])


def test_raw_sparql():
    assert c.post("/api/sparql", json={"query": "SELECT ?l WHERE { ?l a d:Lot }"}).status_code == 200
    assert c.post("/api/sparql", json={"query": "DELETE WHERE { ?s ?p ?o }"}).status_code == 400
    assert c.post("/api/sparql", json={"query": "ASK { d:Lot_L01 a d:Lot }"}).json()["ask"] is True


QUESTIONS = {
    "Quels sont les déchets dangereux ?": lambda r: {x["nom"] for x in r["lignes"]} >= {"Solvants Usages", "Batteries Plomb"},
    "Lots de plus de 500 kg produits par PlastiPack": lambda r: {x["lot"] for x in r["lignes"]} == {"Lot_L02"},
    "Combien de lots ont été recyclés ?": lambda r: r["lignes"][0]["total"] == 5,
    "Qui transporte le lot L04 ?": lambda r: "CamionPlus" in r["reponse"] or "Camion Plus" in r["reponse"],
    "Quelle matière est produite à partir du plastique ?": lambda r: r["lignes"][0]["matiere"] == "Granules PET",
    "Poids total valorisé par procédé": lambda r: len(r["lignes"]) >= 3,
    "Quels centres ne sont pas agréés ?": lambda r: [x["nom"] for x in r["lignes"]] == ["DecharteBizerte"],
    "Montre les lots non conformes": lambda r: [x["lot"] for x in r["lignes"]] == ["Lot_L08"],
    "Parcours du lot 7": lambda r: r["lignes"][0]["producteur"] == "SteelTunis",
    "lots de déchets métalliques de moins de 1000 kg": lambda r: {x["lot"] for x in r["lignes"]} == {"Lot_L11"},
    "Lots produits à Sfax en septembre": lambda r: {x["lot"] for x in r["lignes"]} == {"Lot_L01", "Lot_L07"},
    "lots traités après le 2026-10-01": lambda r: {x["lot"] for x in r["lignes"]} == {"Lot_L10", "Lot_L11", "Lot_L12"},
    "Combien de producteurs ?": lambda r: r["lignes"][0]["total"] == 5,
    "lots transportés par LogiVert non valorisés": lambda r: r["lignes"] == [],
    "quel est le poids total du producteur SteelTunis": lambda r: r["lignes"][0]["total"] == 4180.0,
    "lots de ChimieSud": lambda r: len(r["lignes"]) == 3,
    "Lots du producteur Chimie Sud dangereux non valorisés": lambda r: {x["lot"] for x in r["lignes"]} == {"Lot_L04", "Lot_L08"},
    "lots de PlastyPack": lambda r: len(r["lignes"]) == 2,   # faute de frappe
}


def test_nlq():
    bad = []
    for q, check in QUESTIONS.items():
        r = c.post("/api/nlq", json={"question": q}).json()
        try:
            ok = check(r)
        except Exception as e:  # noqa
            ok = False
        print(("OK  " if ok else "FAIL"), q, "->", r["analyse"]["intention"], r.get("reponse"))
        if not ok:
            bad.append((q, r["analyse"], r["sparql"]))
    assert not bad, bad


def test_inference():
    r = c.get("/api/inference").json()
    print(r["moteur"])
    assert r["LotNonConforme"] == ["Lot_L08"] and "Lot_L04" in r["LotDangereux"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("passed", name)
