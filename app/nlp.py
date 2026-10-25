"""Module NLP / TALN : question en français -> requête SPARQL (sans LLM).

Outils : spaCy (tokenisation, lemmes si fr_core_news_sm est installé, PhraseMatcher),
rapidfuzz (tolérance aux fautes de frappe) et règles linguistiques.

Pipeline : normalisation -> tokenisation spaCy -> liaison d'entités (lexique construit
depuis l'ontologie) -> détection d'intention -> extraction de contraintes (nombres,
dates, classes) -> génération SPARQL (gabarits paramétrés, partagés avec l'API REST).
"""
import re
import unicodedata

import spacy
from rapidfuzz import fuzz
from spacy.matcher import PhraseMatcher

from .store import Store, class_query, lots_query

MONTHS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
          "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}
STOP = {"site", "usages", "usage", "centre", "les", "des", "chutes", "boues"}
CLASS_RULES = [  # (regex sur texte normalisé, classe OWL)
    (r"\bnon[\s-]+dangereu", "DechetNonDangereux"), (r"dangereu|toxique", "DechetDangereux"),
    (r"inerte", "DechetInerte"), (r"plastique", "DechetPlastique"),
    (r"metalli|\bmetal\b|ferraille", "DechetMetallique"), (r"organique", "DechetOrganique"),
    (r"electronique", "DechetElectronique"), (r"chimique", "DechetChimique"),
]
PROCEDE_RULES = [(r"recycl", "P_Recyclage"), (r"composte|compostage", "P_Compostage"),
                 (r"incin", "P_Incineration"), (r"enfou", "P_Enfouissement"),
                 (r"energetique", "P_ValoEnergie")]
GROUP_RULES = [(r"par\s+(procede|traitement)", "procede"), (r"par\s+producteur", "producteur"),
               (r"par\s+centre", "centre"), (r"par\s+transporteur", "transporteur"),
               (r"par\s+(type|dechet)", "dechet")]


def norm(text: str) -> str:
    """Minuscules, sans accents, ponctuation -> espaces."""
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\-.<>]", " ", t)).strip()


def load_spacy():
    """Charge le modèle français complet si possible, sinon le tokenizer français seul."""
    try:
        return spacy.load("fr_core_news_sm", disable=["ner", "parser"]), "fr_core_news_sm"
    except Exception:
        return spacy.blank("fr"), "spacy.blank('fr') (tokenizer seul)"


class NLQ:
    def __init__(self, store: Store):
        self.store = store
        self.nlp, self.model = load_spacy()
        self.refresh()

    # -- lexique construit depuis l'ontologie -----------------------------------
    def refresh(self):
        kinds = {"producteur": "Producteur", "transporteur": "Transporteur",
                 "centre": "CentreTraitement", "dechet": "Dechet", "procede": "ProcedeTraitement",
                 "matiere": "MatiereSecondaire"}
        self.lex = {}  # texte normalisé -> liste (kind, id, label)
        for kind, cls in kinds.items():
            _, rows = self.store.select(class_query(cls))
            for r in rows:
                self._add(norm(r["nom"]), kind, r["x"], r["nom"])
                if kind in ("dechet", "matiere", "producteur", "centre", "transporteur"):
                    for tok in norm(r["nom"]).split():
                        if len(tok) >= 5 and tok not in STOP and not re.match(r"recycl|compost", tok):
                            self._add(tok, kind, r["x"], r["nom"])
        _, rows = self.store.select("SELECT DISTINCT ?v WHERE { ?s d:ville ?v }")
        for r in rows:
            self._add(norm(r["v"]), "ville", r["v"], r["v"])
        self.matcher = PhraseMatcher(self.nlp.vocab, attr="ORTH")
        for key in self.lex:
            self.matcher.add(key, [self.nlp.make_doc(key)])

    def _add(self, key, kind, ident, label):
        entry = (kind, ident, label)
        if entry not in self.lex.setdefault(key, []):
            self.lex[key].append(entry)

    # -- liaison d'entités --------------------------------------------------------
    def link_entities(self, doc):
        spans, taken = [], set()
        for _, s, e in sorted(self.matcher(doc), key=lambda m: -(m[2] - m[1])):
            if taken & set(range(s, e)):
                continue
            taken |= set(range(s, e))
            spans.append((s, e, doc[s:e].text, "exact"))
        # repli : tolérance aux fautes (rapidfuzz) sur les n-grammes non couverts
        toks = [t.text for t in doc]
        for n in (2, 1):
            for s in range(len(toks) - n + 1):
                rng = set(range(s, s + n))
                gram = " ".join(toks[s:s + n])
                if rng & taken or len(gram) < 5 or gram.isdigit():
                    continue
                best = max(self.lex, key=lambda k: fuzz.ratio(gram, k))
                if fuzz.ratio(gram, best) >= 86:
                    taken |= rng
                    spans.append((s, s + n, best, "fuzzy"))
        found = []
        for _, _, key, how in spans:
            for kind, ident, label in self.lex[key]:
                found.append({"kind": kind, "id": ident, "label": label, "match": how, "texte": key})
        return found

    # -- analyse ------------------------------------------------------------------
    def analyse(self, question: str) -> dict:
        t = norm(question)
        doc = self.nlp.make_doc(t)
        lemmas = [norm(tok.lemma_) for tok in self.nlp(question)] if self.model.startswith("fr_") else []
        a = {"texte_normalise": t, "tokens": [x.text for x in doc], "lemmes": lemmas,
             "entites": self.link_entities(doc), "filtres": {}, "intention": "inconnue"}
        f = a["filtres"]

        # nombres : "plus de 500 kg", "moins de 2 tonnes"
        for m in re.finditer(r"(plus de|superieur\w* a|depass\w*|au dessus de|>|moins de|inferieur\w* a|"
                             r"en dessous de|<)\s*(\d+(?:[.,]\d+)?)\s*(kg|kilos?|tonnes?|t)?\b", t):
            val = float(m.group(2).replace(",", "."))
            if (m.group(3) or "").startswith(("t",)) and m.group(3) != "kg":
                val *= 1000
            f["min_poids" if m.group(1) in ("plus de", ">", "au dessus de") or m.group(1).startswith(
                ("superieur", "depass")) else "max_poids"] = val
        # dates
        if m := re.search(r"(apres|depuis|a partir du?)\s+(?:le\s+)?(\d{4}-\d{2}-\d{2})", t):
            f["after"] = m.group(2)
        if m := re.search(r"avant\s+(?:le\s+)?(\d{4}-\d{2}-\d{2})", t):
            f["before"] = m.group(1)
        for name, num in MONTHS.items():
            if re.search(rf"\b{name}\b", t):
                f["month"] = num
        if m := re.search(r"\b(20\d{2})\b", t):
            if "after" not in f and "before" not in f:
                f["year"] = int(m.group(1))
        # classes de déchets et états
        classes = [c for pat, c in CLASS_RULES if re.search(pat, t)]
        if "DechetNonDangereux" in classes and "DechetDangereux" in classes:
            classes.remove("DechetDangereux")
        if re.search(r"non[\s-]+conforme|pas conforme|irregulier", t):
            f["non_conforme"] = True
            classes = [c for c in classes if c != "DechetDangereux"]
        if re.search(r"(non|pas)[\s-]+valoris|(non|pas)[\s-]+recycl", t):
            f["valorise"] = False
        elif re.search(r"valoris", t):
            f["valorise"] = True
        for pat, p in PROCEDE_RULES:
            if re.search(pat, t) and not any(e["kind"] == "procede" for e in a["entites"]) \
                    and "valorise" not in f:
                f["procede"] = p
        if classes:
            f["dechet_class"] = classes
        # entités -> filtres (le premier de chaque type)
        for e in a["entites"]:
            key = e["kind"]
            if key == "ville":
                f.setdefault("ville", e["id"])
            elif key in ("producteur", "transporteur", "centre", "dechet", "procede", "matiere"):
                f.setdefault(key, e["id"])
        for pat, g in GROUP_RULES:
            if re.search(pat, t):
                a["groupe"] = g
        a["lot"] = None
        if m := re.search(r"\blot\s*(?:n\s*)?l?\s?0*(\d{1,3})\b|\bl0*(\d{1,3})\b", t):
            a["lot"] = f"Lot_L{int(m.group(1) or m.group(2)):02d}"
        a["intention"], a["cible"] = self._intent(t, a)
        return a

    def _intent(self, t, a):
        f = a["filtres"]
        if a["lot"]:
            if re.search(r"parcours|trace|historique|detail|tout", t):
                return "tracer_lot", "lot"
            for pat, field in ((r"transport", "transporteur"), (r"qui (a )?(produit|genere)|producteur|origine", "producteur"),
                               (r"centre|qui (a )?trait|traite|recycl", "centre"), (r"procede|comment", "procede"),
                               (r"matiere", "matiere")):
                if re.search(pat, t):
                    a["champ"] = field
                    return "relation_lot", "lot"
            return "tracer_lot", "lot"
        if re.search(r"matiere|a partir d|valorise en|transforme en|devient", t) and \
                (f.get("dechet") or f.get("dechet_class") or "matiere" in f or re.search(r"quelle|quelles", t)):
            return "matiere_depuis_dechet", "dechet"
        cible = "lot"
        for pat, c in ((r"\bcentres?\b|recycleurs?|traitement", "centre"), (r"producteurs?|usines?|entreprises?", "producteur"),
                       (r"transporteurs?", "transporteur"), (r"matieres?", "matiere"),
                       (r"\bdechets?\b", "dechet")):
            if re.search(pat, t):
                cible = c
                break
        numeric = "min_poids" in f or "max_poids" in f
        wants_sum = bool(re.search(r"total|somme|cumul|quantite|tonnage", t) or
                         (re.search(r"poids", t) and not numeric))
        # "lots ...", "poids total du producteur X", "lots traités par Y" -> on interroge les lots
        if re.search(r"\blots?\b|bordereaux?", t) or wants_sum or \
                (cible in ("producteur", "centre", "transporteur") and f.get(cible)):
            cible = "lot"
        if re.search(r"combien|nombre", t):
            return "compter", cible
        if cible == "lot" and wants_sum:
            return "somme_poids", "lot"
        return "lister", cible

    # -- génération SPARQL ----------------------------------------------------------
    def build(self, a: dict):
        it, cible, f = a["intention"], a["cible"], dict(a["filtres"])
        if it in ("tracer_lot", "relation_lot"):
            return lots_query({"lot": a["lot"]}, mode="trace")
        if it == "matiere_depuis_dechet":
            where = ["?dec d:estValoriseEn ?m ; d:nom ?dechet .", "?m d:nom ?matiere ."]
            if f.get("dechet"):
                where.append(f"FILTER(?dec = d:{f['dechet']})")
            for c in f.get("dechet_class", []):
                where.append(f"?dec rdf:type/rdfs:subClassOf* d:{c} .")
            return "SELECT DISTINCT ?dechet ?matiere\nWHERE {\n  " + "\n  ".join(where) + "\n}"
        if it == "compter" and cible == "lot":
            return lots_query(f, mode="count")
        if it == "somme_poids":
            return lots_query(f, mode="sum", group_by=a.get("groupe"))
        if cible == "lot":
            return lots_query(f, mode="list")
        cls = {"centre": "CentreTraitement", "producteur": "Producteur", "transporteur": "Transporteur",
               "matiere": "MatiereSecondaire", "dechet": "Dechet"}[cible]
        if cible == "dechet" and f.get("dechet_class"):
            cls = f["dechet_class"][0]
        agree = None
        if cible == "centre":
            t = a["texte_normalise"]
            agree = False if re.search(r"non[\s-]+agre|pas agre", t) else (True if re.search(r"agre", t) else None)
        return class_query(cls, agree=agree, count=(it == "compter"))

    def answer_text(self, a, cols, rows):
        it = a["intention"]
        if not rows:
            return "Aucun résultat pour cette question."
        if it == "compter" or (it == "somme_poids" and len(rows) == 1 and "total" in rows[0] and len(cols) == 1):
            v = rows[0]["total"]
            return f"Résultat : {v:g} kg" if it == "somme_poids" else f"Résultat : {v}"
        if it in ("tracer_lot", "relation_lot"):
            r = rows[0]
            if it == "relation_lot":
                label = {"transporteur": "transporté par", "producteur": "produit par", "centre": "traité par",
                         "procede": "soumis au procédé", "matiere": "transformé en"}[a["champ"]]
                return f"{r['nom']} est {label} : {r.get(a['champ']) or 'non renseigné'}."
            return (f"{r['nom']} : {r['dechet']} produit par {r['producteur']}, transporté par "
                    f"{r['transporteur']}, traité par {r['centre']} ({r['procede']})"
                    + (f", donnant : {r['matiere']}." if r.get("matiere") else "."))
        return f"{len(rows)} résultat(s)."

    def ask(self, question: str) -> dict:
        a = self.analyse(question)
        out = {"question": question, "modele_spacy": self.model,
               "analyse": {k: a[k] for k in ("intention", "cible", "filtres", "lot", "entites") if k in a}}
        if a["intention"] == "inconnue":
            out.update(sparql=None, colonnes=[], lignes=[], reponse="Question non comprise.")
            return out
        q = self.build(a)
        cols, rows = self.store.select(q)
        out.update(sparql=q, colonnes=cols, lignes=rows, reponse=self.answer_text(a, cols, rows))
        return out
