# ontologie_dechets.py
# Ontologie "Gestion des déchets / économie circulaire" avec Owlready2
# Usage : python ontologie_dechets.py
# Sortie : dechets.owl (RDF/XML). Le raisonneur HermiT (Java) est optionnel.

import datetime
from owlready2 import *

ONTO_IRI = "http://esprit.tn/dechets.owl"   # IRI de base -> préfixe SPARQL : <http://esprit.tn/dechets.owl#>
onto = get_ontology(ONTO_IRI)

# ----------------------------------------------------------------------
# 1) CLASSES
# ----------------------------------------------------------------------
with onto:
    # --- Déchets (deux axes : dangerosité et nature du matériau) ---
    class Dechet(Thing): pass
    class DechetDangereux(Dechet): pass
    class DechetNonDangereux(Dechet): pass
    class DechetInerte(Dechet): pass
    class DechetPlastique(Dechet): pass
    class DechetMetallique(Dechet): pass
    class DechetOrganique(Dechet): pass
    class DechetElectronique(Dechet): pass
    class DechetChimique(Dechet): pass

    # --- Acteurs ---
    class Acteur(Thing): pass
    class Producteur(Acteur): pass
    class Transporteur(Acteur): pass
    class CentreTraitement(Acteur): pass
    class Recycleur(CentreTraitement): pass

    # --- Procédés de traitement ---
    class ProcedeTraitement(Thing): pass
    class ProcedeValorisant(ProcedeTraitement): pass
    class ProcedeElimination(ProcedeTraitement): pass
    class Recyclage(ProcedeValorisant): pass
    class Compostage(ProcedeValorisant): pass
    class ValorisationEnergetique(ProcedeValorisant): pass
    class Incineration(ProcedeElimination): pass
    class Enfouissement(ProcedeElimination): pass

    # --- Autres ---
    class Lot(Thing): pass
    class MatiereSecondaire(Thing): pass
    class Site(Thing): pass

# ----------------------------------------------------------------------
# 2) OBJECT PROPERTIES
# ----------------------------------------------------------------------
with onto:
    class produitPar(ObjectProperty, FunctionalProperty):
        domain = [Lot]; range = [Producteur]

    class contientDechet(ObjectProperty):
        domain = [Lot]; range = [Dechet]

    class transportePar(ObjectProperty):
        domain = [Lot]; range = [Transporteur]

    class traitePar(ObjectProperty):
        domain = [Lot]; range = [CentreTraitement]

    class subitProcede(ObjectProperty):
        domain = [Lot]; range = [ProcedeTraitement]

    class produitMatiere(ObjectProperty):
        domain = [Lot]; range = [MatiereSecondaire]

    class provientDe(ObjectProperty):            # inverse de produitMatiere
        domain = [MatiereSecondaire]; range = [Lot]
        inverse_property = produitMatiere

    class estValoriseEn(ObjectProperty):
        domain = [Dechet]; range = [MatiereSecondaire]

    class localiseA(ObjectProperty):
        domain = [Acteur]; range = [Site]

# ----------------------------------------------------------------------
# 3) DATA PROPERTIES
# ----------------------------------------------------------------------
with onto:
    class nom(DataProperty, FunctionalProperty):
        domain = [Thing]; range = [str]

    class poidsKg(DataProperty, FunctionalProperty):
        domain = [Lot]; range = [float]

    class dateProduction(DataProperty, FunctionalProperty):
        domain = [Lot]; range = [datetime.datetime]   # xsd:dateTime (xsd:date n'est pas supporté par HermiT)

    class numeroBordereau(DataProperty, FunctionalProperty):
        domain = [Lot]; range = [str]

    class codeDechet(DataProperty, FunctionalProperty):
        domain = [Dechet]; range = [str]

    class tauxValorisation(DataProperty, FunctionalProperty):
        domain = [CentreTraitement]; range = [float]

    class estAgree(DataProperty, FunctionalProperty):
        domain = [CentreTraitement]; range = [bool]

    class ville(DataProperty, FunctionalProperty):
        domain = [Site]; range = [str]

# ----------------------------------------------------------------------
# 4) AXIOMES
# ----------------------------------------------------------------------
with onto:
    # a) Disjonctions
    AllDisjoint([DechetDangereux, DechetNonDangereux, DechetInerte])
    AllDisjoint([Producteur, Transporteur, CentreTraitement])
    AllDisjoint([ProcedeValorisant, ProcedeElimination])

    # b) Restriction de cardinalité : un lot a exactement un producteur
    Lot.is_a.append(produitPar.exactly(1, Producteur))

    # c) Un lot doit contenir au moins un déchet
    Lot.is_a.append(contientDechet.min(1, Dechet))

    # d) Classes définies (équivalences) -> inférées par le raisonneur
    class LotDangereux(Lot):
        equivalent_to = [Lot & contientDechet.some(DechetDangereux)]

    class LotValorise(Lot):
        equivalent_to = [Lot & subitProcede.some(ProcedeValorisant)]

    class CentreNonAgree(CentreTraitement):
        equivalent_to = [CentreTraitement & estAgree.value(False)]

    # Un lot dangereux traité par un centre non agréé est non conforme
    class LotNonConforme(Lot):
        equivalent_to = [LotDangereux & traitePar.some(CentreNonAgree)]

# ----------------------------------------------------------------------
# 5) INDIVIDUS (jeu de données de démonstration)
# ----------------------------------------------------------------------
def label(name):
    return name.replace("_", " ")

with onto:
    # --- Sites ---
    sites_data = {
        "Site_Sfax_ZI": "Sfax", "Site_Ben_Arous": "Ben Arous", "Site_Bizerte": "Bizerte",
        "Site_Sousse": "Sousse", "Site_Tunis_Nord": "Tunis", "Site_Gabes": "Gabès",
        "Site_Nabeul": "Nabeul", "Site_Monastir": "Monastir",
    }
    sites = {}
    for n, v in sites_data.items():
        s = Site(n); s.nom = label(n); s.ville = v
        sites[n] = s

    # --- Producteurs ---
    prod_data = {
        "SteelTunis": "Site_Sfax_ZI", "PlastiPack": "Site_Ben_Arous",
        "ChimieSud": "Site_Gabes", "ElectroSousse": "Site_Sousse",
        "AgroDelice": "Site_Nabeul",
    }
    producteurs = {}
    for n, site in prod_data.items():
        p = Producteur(n); p.nom = label(n); p.localiseA = [sites[site]]
        producteurs[n] = p

    # --- Transporteurs ---
    transp_data = {"TransEco": "Site_Tunis_Nord", "LogiVert": "Site_Sousse",
                   "CamionPlus": "Site_Sfax_ZI"}
    transporteurs = {}
    for n, site in transp_data.items():
        t = Transporteur(n); t.nom = label(n); t.localiseA = [sites[site]]
        transporteurs[n] = t

    # --- Centres de traitement : (classe, site, agréé, taux de valorisation) ---
    centres_data = {
        "RecyTunis":       (Recycleur,        "Site_Ben_Arous", True,  0.85),
        "EcoCompost":      (CentreTraitement, "Site_Nabeul",    True,  0.90),
        "IncinerOuest":    (CentreTraitement, "Site_Bizerte",   True,  0.40),
        "DecharteBizerte": (CentreTraitement, "Site_Bizerte",   False, 0.00),
        "ChimTrait":       (CentreTraitement, "Site_Gabes",     True,  0.60),
    }
    centres = {}
    for n, (cls, site, agree, taux) in centres_data.items():
        c = cls(n); c.nom = label(n); c.localiseA = [sites[site]]
        c.estAgree = agree; c.tauxValorisation = taux
        centres[n] = c

    # --- Matières secondaires ---
    matieres = {}
    for n in ["Granules_PET", "Acier_Recycle", "Compost", "Metaux_Precieux",
              "Plomb_Recycle", "Granulats_Recycles"]:
        m = MatiereSecondaire(n); m.nom = label(n)
        matieres[n] = m

    # --- Types de déchets : (classes, code LER indicatif, matière issue de la valorisation) ---
    dechets_data = {
        "Bouteilles_PET":       ([DechetPlastique, DechetNonDangereux],    "15 01 02", "Granules_PET"),
        "Chutes_Acier":         ([DechetMetallique, DechetNonDangereux],   "12 01 01", "Acier_Recycle"),
        "Epluchures_Legumes":   ([DechetOrganique, DechetNonDangereux],    "02 01 03", "Compost"),
        "Cartes_Electroniques": ([DechetElectronique, DechetDangereux],    "16 02 13", "Metaux_Precieux"),
        "Solvants_Usages":      ([DechetChimique, DechetDangereux],        "14 06 03", None),
        "Batteries_Plomb":      ([DechetElectronique, DechetDangereux],    "16 06 01", "Plomb_Recycle"),
        "Gravats_Beton":        ([DechetInerte],                           "17 01 01", "Granulats_Recycles"),
        "Boues_Industrielles":  ([DechetChimique, DechetDangereux],        "19 02 05", None),
    }
    dechets = {}
    for n, (classes, code, mat) in dechets_data.items():
        d = Dechet(n)
        d.is_a = list(classes)          # typage multiple de l'individu
        d.nom = label(n); d.codeDechet = code
        if mat:
            d.estValoriseEn = [matieres[mat]]
        dechets[n] = d

    # --- Procédés ---
    procedes = {
        "P_Recyclage":    Recyclage("P_Recyclage"),
        "P_Compostage":   Compostage("P_Compostage"),
        "P_ValoEnergie":  ValorisationEnergetique("P_ValoEnergie"),
        "P_Incineration": Incineration("P_Incineration"),
        "P_Enfouissement": Enfouissement("P_Enfouissement"),
    }
    for n, p in procedes.items():
        p.nom = label(n[2:])

    # --- Lots : (producteur, déchet, poids, date, transporteur, centre, procédé, matière) ---
    lots_data = [
        ("SteelTunis",    "Chutes_Acier",         1200, (2026, 9, 2),  "TransEco",   "RecyTunis",       "P_Recyclage",    "Acier_Recycle"),
        ("PlastiPack",    "Bouteilles_PET",        800, (2026, 9, 5),  "LogiVert",   "RecyTunis",       "P_Recyclage",    "Granules_PET"),
        ("AgroDelice",    "Epluchures_Legumes",    450, (2026, 9, 8),  "LogiVert",   "EcoCompost",      "P_Compostage",   "Compost"),
        ("ChimieSud",     "Solvants_Usages",       300, (2026, 9, 10), "CamionPlus", "ChimTrait",       "P_Incineration", None),
        ("ElectroSousse", "Cartes_Electroniques",  120, (2026, 9, 12), "TransEco",   "RecyTunis",       "P_Recyclage",    "Metaux_Precieux"),
        ("ElectroSousse", "Batteries_Plomb",       600, (2026, 9, 15), "TransEco",   "RecyTunis",       "P_Recyclage",    "Plomb_Recycle"),
        ("SteelTunis",    "Gravats_Beton",        2500, (2026, 9, 18), "CamionPlus", "RecyTunis",       "P_Recyclage",    "Granulats_Recycles"),
        ("ChimieSud",     "Boues_Industrielles",   900, (2026, 9, 20), "CamionPlus", "DecharteBizerte", "P_Enfouissement", None),
        ("PlastiPack",    "Bouteilles_PET",        350, (2026, 9, 25), "LogiVert",   "IncinerOuest",    "P_ValoEnergie",  None),
        ("AgroDelice",    "Epluchures_Legumes",    700, (2026, 10, 1), "LogiVert",   "EcoCompost",      "P_Compostage",   "Compost"),
        ("SteelTunis",    "Chutes_Acier",          480, (2026, 10, 5), "TransEco",   "DecharteBizerte", "P_Enfouissement", None),
        ("ChimieSud",     "Solvants_Usages",       150, (2026, 10, 8), "CamionPlus", "ChimTrait",       "P_ValoEnergie",  None),
    ]
    for i, (prod, dech, poids, dt, trans, centre, proc, mat) in enumerate(lots_data, start=1):
        lot = Lot(f"Lot_L{i:02d}")
        lot.nom = f"Lot L{i:02d}"
        lot.numeroBordereau = f"BSD-2026-{i:03d}"
        lot.poidsKg = float(poids)
        lot.dateProduction = datetime.datetime(*dt)
        lot.produitPar = producteurs[prod]
        lot.contientDechet = [dechets[dech]]
        lot.transportePar = [transporteurs[trans]]
        lot.traitePar = [centres[centre]]
        lot.subitProcede = [procedes[proc]]
        if mat:
            lot.produitMatiere = [matieres[mat]]

# ----------------------------------------------------------------------
# 6) SAUVEGARDE (RDF/XML, relisible avec rdflib : g.parse("dechets.owl", format="xml"))
# ----------------------------------------------------------------------
onto.save(file="dechets.owl", format="rdfxml")
print(f"Ontologie sauvegardée : dechets.owl")
print(f"Classes : {len(list(onto.classes()))} | ObjectProperty : {len(list(onto.object_properties()))} "
      f"| DataProperty : {len(list(onto.data_properties()))} | Individus : {len(list(onto.individuals()))}")

# ----------------------------------------------------------------------
# 7) RAISONNEUR HermiT (nécessite Java)
# ----------------------------------------------------------------------
try:
    with onto:
        sync_reasoner()      # HermiT par défaut
    print("\n--- Après raisonnement (HermiT) ---")
    print("Lots dangereux     :", sorted(i.name for i in onto.LotDangereux.instances()))
    print("Lots valorisés     :", sorted(i.name for i in onto.LotValorise.instances()))
    print("Lots non conformes :", sorted(i.name for i in onto.LotNonConforme.instances()))
    print("Centres non agréés :", sorted(i.name for i in onto.CentreNonAgree.instances()))
except Exception as e:
    print("\nRaisonneur non disponible (Java/HermiT requis) :", e)
