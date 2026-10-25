"""Validation SHACL (pyshacl) des lots : contraintes structurelles + règle métier réglementaire."""
import os

from pyshacl import validate
from rdflib import RDF, Graph, Namespace

SH = Namespace("http://www.w3.org/ns/shacl#")
SHAPES_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "shapes.ttl")
_shapes = Graph().parse(SHAPES_FILE, format="turtle")


def violations(data: Graph, focus: str | None = None) -> list[dict]:
    """Retourne les violations SHACL (éventuellement limitées à un lot)."""
    _, report, _ = validate(data, shacl_graph=_shapes, inference="none")
    out = []
    for r in report.subjects(RDF.type, SH.ValidationResult):
        lot = str(report.value(r, SH.focusNode)).split("#")[-1]
        if focus and lot != focus:
            continue
        path = report.value(r, SH.resultPath)
        out.append({"lot": lot, "propriete": str(path).split("#")[-1] if path else None,
                    "message": str(report.value(r, SH.resultMessage))})
    return sorted(out, key=lambda v: (v["lot"], v["message"]))
