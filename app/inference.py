"""Raisonnement : HermiT via Owlready2 (Java requis) avec repli sur des règles SPARQL équivalentes."""
import pathlib

from .store import Store, lots_query

CLASSES = ["LotDangereux", "LotValorise", "LotNonConforme", "CentreNonAgree"]


def run_inference(store: Store) -> dict:
    try:
        from owlready2 import World, sync_reasoner
        world = World()
        # Owlready2 converts file:// URIs back to local paths by removing the
        # "file://" prefix. On Windows, Path.as_uri() yields file:///C:/..., which
        # becomes the invalid /C:/... path. Keep the drive letter immediately
        # after file:// so Owlready2 opens the local ontology correctly.
        uri = pathlib.Path(store.path).as_uri().replace("file:///", "file://", 1)
        onto = world.get_ontology(uri).load()
        with onto:
            sync_reasoner(world)
        res = {c: sorted(i.name for i in getattr(onto, c).instances()) for c in CLASSES}
        return {"moteur": "HermiT (Owlready2)", **res}
    except Exception as exc:  # Java absent, etc.
        def ids(f):
            return sorted({r["lot"] for r in store.select(lots_query(f))[1]})
        _, centres = store.select(
            "SELECT ?x WHERE { ?x d:estAgree ?a . FILTER(?a = false) }")
        return {"moteur": f"Règles SPARQL équivalentes (HermiT indisponible : {type(exc).__name__})",
                "LotDangereux": ids({"dechet_class": ["DechetDangereux"]}),
                "LotValorise": ids({"valorise": True}),
                "LotNonConforme": ids({"non_conforme": True}),
                "CentreNonAgree": sorted(r["x"] for r in centres)}
