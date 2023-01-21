import sys
import cadquery as cq, pcbnew
from typing import Callable, Dict, List, Tuple, TypeAlias, Union
import traceback
import warnings
import sys

from OCP.Geom import Geom_BSplineCurve
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge

def warn_with_traceback(message, category, filename, lineno, file=None, line=None):
    log = file if hasattr(file,'write') else sys.stderr
    traceback.print_stack(file=log)
    log.write(warnings.formatwarning(message, category, filename, lineno, line))

warnings.showwarning = warn_with_traceback
iu2mm = pcbnew.Iu2Millimeter
Component: TypeAlias = Union[str, pcbnew.FOOTPRINT]

class Board:
    def __init__(self, name: str) -> None:
        self.board: pcbnew.BOARD = pcbnew.LoadBoard(name)
        self.center: pcbnew.wxPoint = self.board.GetDesignSettings().GetAuxOrigin()

    def p(self, l: pcbnew.wxPoint) -> Tuple[float, float]:
        rel = l - self.center
        return iu2mm(rel.x), -iu2mm(rel.y)

    @staticmethod
    def trans_model_path(p: str) -> str:
        envars = {"KIPRJMOD": ".", "KICAD6_3DMODEL_DIR": "/usr/share/kicad/3dmodels"}
        for k, v in envars.items():
            p = p.replace(f"${{{k}}}", v)
        if p.endswith(".wrl"):
            p = p[:-4] + ".step"
        return p
    
    def fp(self, comp: Component) -> pcbnew.FOOTPRINT:
        return comp if isinstance(comp, pcbnew.FOOTPRINT) else self.board.FindFootprintByReference(comp)

    def fps_where(self, f: Callable[[pcbnew.FOOTPRINT], bool]) -> list[pcbnew.FOOTPRINT]:
        return [fp for fp in self.fps() if f(fp)]

    def fps_with_val(self, v: str) -> list[pcbnew.FOOTPRINT]:
        return self.fps_where(lambda fp: fp.GetValue() == v)

    @staticmethod
    def ref(comp: Component) -> str:
        return comp.GetReference() if isinstance(comp, pcbnew.FOOTPRINT) else comp
    
    def pos(self, comp: Component) -> Tuple[float, float]:
        return self.p(self.fp(comp).GetPosition())

    def courtyard(self, comp: Component, front: bool = True) -> cq.Sketch:
        return self.convert_shape(self.courtyard_raw(comp, front))

    def courtyard_raw(self, comp: Component, front: bool = True) -> List[pcbnew.PCB_SHAPE]:
        return self.layer_raw_of(comp, (pcbnew.F_CrtYd if front else pcbnew.B_CrtYd))
    
    def fps(self) -> List[pcbnew.FOOTPRINT]:
        return self.board.GetFootprints()
    
    def edges(self) -> cq.Sketch:
        return self.layer(pcbnew.Edge_Cuts)

    def edges_raw(self) -> List[pcbnew.PCB_SHAPE]:
        return self.layer_raw(pcbnew.Edge_Cuts)

    def layer(self, layer: int) -> cq.Sketch:
        return self.convert_shape(self.layer_raw(layer))

    def layer_raw(self, layer: int) -> List[pcbnew.PCB_SHAPE]:
        return [g for g in self.board.GetDrawings() if g.GetLayer() == layer]

    def layer_of(self, comp: Component, layer: int) -> cq.Sketch:
        return self.convert_shape(self.layer_raw_of(comp, layer))

    def layer_raw_of(self, comp: Component, layer: int) -> List[pcbnew.PCB_SHAPE]:
        return [g for g in self.fp(comp).GraphicalItems() if g.GetLayer() == layer]

    def height(self, comp: Component, def_h: float) -> float:
        try:
            h = max(cq.importers.importStep(Board.trans_model_path(m.m_Filename)).faces(">Z").val().Center().z
                    + m.m_Offset.z
                    for m in self.fp(comp).Models())
            h += max(0.2, h * 0.1)
            return h
        except:
            return def_h

    def max_height(self, hmap: Dict[str, float], def_h: float, comps: List[Component]) -> float:
        return max(self.height(comp, hmap[ref] if (ref := Board.ref(comp)) in hmap else def_h) for comp in comps)

    def convert_shape(self, shapes: List[pcbnew.PCB_SHAPE]) -> cq.Sketch:
        minmax = lambda *l: (min(l), max(l))
        sketch = cq.Sketch()
        line, full = False, 0
        for shape in shapes:
            match shape.GetShape():
                case pcbnew.SHAPE_T_ARC:
                    line = True
                    sketch = sketch.arc(*[self.p(l) for l in (shape.GetStart(), shape.GetArcMid(), shape.GetEnd())])
                case pcbnew.SHAPE_T_SEGMENT:
                    line = True
                    sketch = sketch.segment(*[self.p(l) for l in (shape.GetStart(), shape.GetEnd())])
                case pcbnew.SHAPE_T_CIRCLE:
                    full += 1
                    sketch = sketch.push([self.p(shape.GetCenter())]).circle(iu2mm(shape.GetRadius()))
                case pcbnew.SHAPE_T_RECT:
                    full += 1
                    start, end = shape.GetStart(), shape.GetEnd()
                    (x, X), (y, Y) = minmax(start.x, end.x), minmax(start.y, end.y)
                    sketch = sketch.push([self.p(shape.GetCenter())]).rect(iu2mm(X - x), iu2mm(Y - y)).reset()
                case pcbnew.SHAPE_T_BEZIER:
                    line = True
                    sketch = sketch.edge(bspline(list(map(self.p, [shape.GetStart(), shape.GetBezierC1(), shape.GetBezierC2(), shape.GetEnd()]))))
                case pcbnew.SHAPE_T_POLY:
                    full += 1
                    shape = shape.GetPolyShape()
                    points = [self.p(shape.CVertex(i).getWxPoint()) for i in range(shape.VertexCount())]
                    sketch = sketch.polygon(points + [points[0]])
                case s:
                    raise NotImplementedError(f"unhandled shape type: {s}")
        if full > 0 and line:
            warnings.warn("convert_shape: both complete and incomplete shapes used, shape may be undefined")
        if full > 1:
            warnings.warn("convert_shape: more than 1 complete shapes used, shape may be undefined")
        return sketch.assemble() if line else sketch

def bspline(points: List[Tuple[float, float]]) -> cq.Edge:
    assert len(points) == 4
    pnts = TColgp_Array1OfPnt(1, 4)
    for i, v in enumerate(points):
        pnts.SetValue(i + 1, cq.Vector(v).toPnt())
    knots = TColStd_Array1OfReal(1, 2)
    knots.SetValue(1, 0)
    knots.SetValue(2, 1)
    mults = TColStd_Array1OfInteger(1, 2)
    mults.SetValue(1, 4)
    mults.SetValue(2, 4)
    return cq.Edge(BRepBuilderAPI_MakeEdge(Geom_BSplineCurve(pnts, knots, mults, 3)).Edge())
