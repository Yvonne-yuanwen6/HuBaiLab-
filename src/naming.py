"""
LatticeLab 算例命名规则（目录 / 文件名 / Abaqus 作业名一致）。

Slug 格式（目录名 / INP 基名 / Abaqus job 名一致，≤38 字符）::

    {杆型}_{单胞}_{杆径}_{行程}

**杆型**（直撑角度 **或** 余弦拱参数）:

- ``str_a45``       直撑与框架竖杆夹角 45°
- ``str_ez50``      直撑在竖棱高度 50%（未设角度时）
- ``c25n12``        余弦撑：拱峰值 h/L=0.25，12 折线段（w=(h/2)[1-cos(2πs)]）

**单胞**（边长 + O 点高度比）:

- ``L10_Oh1p3``  单胞边长 10 mm；O 点高出顶面比例 1/3

**杆径**（框架 / 斜撑 / 竖杆，mm）:

- ``rf0p5_rs0p4_rv0p6``

**行程**:

- ``q`` / ``f``  快速 / 整段压缩（正向压，顶板下压）
- ``qb`` / ``fb``  快速 / 整段自下而上（反向压）

路径（``export`` / ``jobs`` / ``post`` 结构一致）::

    {top_down|bottom_up}/{straight|cosine}/{角度键}/{slug}/

- ``top_down/straight/a55/``   正向压，直杆 55°
- ``bottom_up/cosine/h25n12/``  反向压，余弦拱 h/L=0.25、12 段

示例 slug::

    str_a45_L10_Oh0p5_rf0p5_rs0p4_rv0p6_f
    c25n12_L10_Oh0p5_rf0p5_rs0p4_rv0p6_q
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from src.paths import ABAQUS_JOBS, ABAQUS_POST, EXPORT_ROOT, OUTPUT_ROOT

StrokeKind = Literal["quick", "full", "quick_bu", "full_bu"]
LoadDirKind = Literal["top_down", "bottom_up"]
RodKind = Literal["straight", "cosine"]

_MAX_JOB_NAME_LEN = 38
_SLUG_SAFE = re.compile(r"[^A-Za-z0-9._-]+")

_STROKE_TOKEN = {
    "quick": "q",
    "full": "f",
    "quick_bu": "qb",
    "full_bu": "fb",
}

_LOAD_DIR_LABEL = {
    "top_down": "正向压",
    "bottom_up": "反向压",
}


def fmt_dim(value: float, *, prefix: str = "") -> str:
    """Format a length/radius for slugs: 0.5 -> rf0p5 when prefix='rf'."""
    text = f"{float(value):g}".replace(".", "p")
    return f"{prefix}{text}" if prefix else text


def o_height_token(gen) -> str:
    """O 点高出单胞顶面的高度比 height_ratio，如 1/3 -> Oh1p3。"""
    hr = float(getattr(gen, "height_ratio", 0.5))
    for num, den, tok in (
        (1, 3, "Oh1p3"),
        (1, 2, "Oh0p5"),
        (1, 4, "Oh0p25"),
    ):
        if abs(hr - num / den) < 1e-6:
            return tok
    return f"Oh{fmt_dim(hr)}"


def support_type_token(gen) -> str:
    """
    杆件类型 + 单胞角度参数.

    - ``str_a45``     直撑，与竖杆夹角 45°
    - ``str_ez79``    直撑，竖棱连接高度 79%
    - ``cos25n12``    余弦撑，拱峰值 h/L=0.25，12 折线段
    """
    curve = str(getattr(gen, "support_curve", "straight")).lower()
    if curve == "cosine":
        h_ratio = getattr(gen, "cosine_amplitude_ratio", 0.2)
        seg = getattr(gen, "cosine_n_segments", 10)
        return f"c{int(round(float(h_ratio) * 100)):02d}n{int(seg)}"

    angle = getattr(gen, "support_vertical_angle_deg", None)
    if angle is not None:
        return f"str_a{float(angle):g}"
    frac = float(getattr(gen, "edge_z_frac", 0.5))
    return f"str_ez{int(round(frac * 100)):02d}"


def cell_size_token(gen) -> str:
    """单胞边长 + O 点高度比。"""
    return f"L{fmt_dim(gen.L)}_{o_height_token(gen)}"


def beam_radii_token(gen) -> str:
    """框架 / 斜撑 / 竖杆半径（mm）。"""
    return (
        f"{fmt_dim(float(gen.r_frame), prefix='rf')}_"
        f"{fmt_dim(float(gen.r_support), prefix='rs')}_"
        f"{fmt_dim(float(gen.r_vertical), prefix='rv')}"
    )


def stroke_token(stroke: StrokeKind) -> str:
    return _STROKE_TOKEN.get(stroke, str(stroke))


def angle_key_for_gen(gen) -> str:
    """目录分组键：直杆按角度 a55 / ez50，余弦按拱参数 h25n12。"""
    curve = str(getattr(gen, "support_curve", "straight")).lower()
    if curve == "cosine":
        h_ratio = getattr(gen, "cosine_amplitude_ratio", 0.2)
        seg = getattr(gen, "cosine_n_segments", 10)
        return f"h{int(round(float(h_ratio) * 100)):02d}n{int(seg)}"
    angle = getattr(gen, "support_vertical_angle_deg", None)
    if angle is not None:
        return f"a{float(angle):g}"
    frac = float(getattr(gen, "edge_z_frac", 0.5))
    return f"ez{int(round(frac * 100)):02d}"


def rod_kind_for_gen(gen) -> RodKind:
    curve = str(getattr(gen, "support_curve", "straight")).lower()
    return "cosine" if curve == "cosine" else "straight"


def load_dir_for_stroke(stroke: StrokeKind) -> LoadDirKind:
    return "bottom_up" if stroke in ("quick_bu", "full_bu") else "top_down"


def load_dir_label(load_dir: LoadDirKind) -> str:
    return _LOAD_DIR_LABEL[load_dir]


@dataclass(frozen=True)
class CaseLayout:
    rod_kind: RodKind
    angle_key: str
    load_dir: LoadDirKind

    @property
    def rel_dir(self) -> Path:
        return Path(self.load_dir) / self.rod_kind / self.angle_key


def case_layout(gen, *, stroke: StrokeKind) -> CaseLayout:
    return CaseLayout(
        rod_kind=rod_kind_for_gen(gen),
        angle_key=angle_key_for_gen(gen),
        load_dir=load_dir_for_stroke(stroke),
    )


def build_case_slug(
    gen,
    *,
    stroke: StrokeKind,
    nx: int = 3,
    ny: int = 3,
    nz: int = 3,
) -> str:
    """Build filesystem-safe case slug (also used as Abaqus job name)."""
    parts = [
        support_type_token(gen),
        cell_size_token(gen),
        beam_radii_token(gen),
        stroke_token(stroke),
    ]
    if (int(nx), int(ny), int(nz)) != (3, 3, 3):
        parts.insert(-2, f"{int(nx)}x{int(ny)}x{int(nz)}")
    slug = "_".join(parts)
    slug = _SLUG_SAFE.sub("_", slug).strip("_")
    if len(slug) > _MAX_JOB_NAME_LEN:
        raise ValueError(
            f"Case slug too long for Abaqus job name ({len(slug)} > {_MAX_JOB_NAME_LEN}): {slug}"
        )
    return slug


def build_geometry_tag(gen, *, nx: int = 3, ny: int = 3, nz: int = 3) -> str:
    """INP Heading 中的几何标识（不含行程 q/f/qb/fb）。"""
    parts = [support_type_token(gen), cell_size_token(gen), beam_radii_token(gen)]
    if (int(nx), int(ny), int(nz)) != (3, 3, 3):
        parts.append(f"{int(nx)}x{int(ny)}x{int(nz)}")
    return "_".join(parts)


def manifest_extra(gen, *, geom_tag: str) -> dict:
    """Human-readable fields stored in case_manifest / meta."""
    extra = {
        "geometry_tag": geom_tag,
        "support_type": support_type_token(gen),
        "cell_size_mm": float(gen.L),
        "o_height_ratio": float(gen.height_ratio),
        "o_height_token": o_height_token(gen),
        "edge_z_frac": float(gen.resolved_edge_z_frac()),
        "beam_radii_token": beam_radii_token(gen),
        "r_frame_mm": float(gen.r_frame),
        "r_support_mm": float(gen.r_support),
        "r_vertical_mm": float(gen.r_vertical),
    }
    curve = str(getattr(gen, "support_curve", "straight")).lower()
    if curve == "cosine":
        extra["cosine_h_ratio"] = float(gen.cosine_amplitude_ratio)
        extra["cosine_n_segments"] = int(gen.cosine_n_segments)
        extra["cosine_formula"] = "w=(h/2)[1-cos(2*pi*s)]"
    else:
        extra["support_angle_deg"] = float(gen.resolved_support_vertical_angle_deg())
    return extra


@dataclass(frozen=True)
class CasePaths:
    """All standard paths for one lattice compression case."""

    slug: str
    stroke: StrokeKind
    layout: CaseLayout
    export_dir: Path
    job_dir: Path
    post_dir: Path
    compression_inp: Path
    topology_b31_inp: Path
    meta_json: Path
    nodes_csv: Path
    beams_csv: Path
    wireframe_png: Path
    odb: Path
    stress_strain_csv: Path
    stress_strain_raw_csv: Path
    stress_strain_png: Path
    yield_json: Path
    case_manifest: Path
    active_manifest: Path

    @property
    def rod_kind(self) -> RodKind:
        return self.layout.rod_kind

    @property
    def angle_key(self) -> str:
        return self.layout.angle_key

    @property
    def load_dir(self) -> LoadDirKind:
        return self.layout.load_dir

    @property
    def load_dir_label(self) -> str:
        return load_dir_label(self.layout.load_dir)

    @property
    def job_name(self) -> str:
        return self.slug

    @property
    def job_inp_name(self) -> str:
        return f"{self.slug}.inp"

    def to_dict(self) -> dict[str, str]:
        data = {k: str(v) for k, v in asdict(self).items() if k != "layout"}
        data["rod_kind"] = self.layout.rod_kind
        data["angle_key"] = self.layout.angle_key
        data["load_dir"] = self.layout.load_dir
        data["load_dir_label"] = self.load_dir_label
        return data


def _build_case_paths(slug: str, *, stroke: StrokeKind, layout: CaseLayout) -> CasePaths:
    case_root = layout.rel_dir / slug
    export_dir = EXPORT_ROOT / case_root
    job_dir = ABAQUS_JOBS / case_root
    post_dir = ABAQUS_POST / case_root
    return CasePaths(
        slug=slug,
        stroke=stroke,
        layout=layout,
        export_dir=export_dir,
        job_dir=job_dir,
        post_dir=post_dir,
        compression_inp=export_dir / f"{slug}.inp",
        topology_b31_inp=export_dir / f"{slug}_topology_b31.inp",
        meta_json=export_dir / f"{slug}_meta.json",
        nodes_csv=export_dir / f"{slug}_nodes.csv",
        beams_csv=export_dir / f"{slug}_beams.csv",
        wireframe_png=export_dir / f"{slug}_wireframe.png",
        odb=job_dir / f"{slug}.odb",
        stress_strain_csv=post_dir / f"{slug}_stress_strain.csv",
        stress_strain_raw_csv=post_dir / f"{slug}_stress_strain_raw.csv",
        stress_strain_png=post_dir / f"{slug}_stress_strain.png",
        yield_json=post_dir / f"{slug}_yield.json",
        case_manifest=export_dir / "case_manifest.json",
        active_manifest=OUTPUT_ROOT / "active_case.json",
    )


def case_paths_for_case(
    gen,
    *,
    stroke: StrokeKind,
    nx: int = 3,
    ny: int = 3,
    nz: int = 3,
) -> CasePaths:
    """Build slug + nested export/jobs/post paths from generator geometry."""
    slug = build_case_slug(gen, stroke=stroke, nx=nx, ny=ny, nz=nz)
    layout = case_layout(gen, stroke=stroke)
    return _build_case_paths(slug, stroke=stroke, layout=layout)


def case_paths_for_slug(
    slug: str,
    *,
    stroke: StrokeKind,
    layout: CaseLayout | None = None,
) -> CasePaths:
    """Resolve paths from slug; pass ``layout`` for nested dirs (or legacy flat if omitted)."""
    if layout is None:
        layout = CaseLayout(rod_kind="straight", angle_key="_legacy", load_dir=load_dir_for_stroke(stroke))
        export_dir = EXPORT_ROOT / slug
        job_dir = ABAQUS_JOBS / slug
        post_dir = ABAQUS_POST / slug
        return CasePaths(
            slug=slug,
            stroke=stroke,
            layout=layout,
            export_dir=export_dir,
            job_dir=job_dir,
            post_dir=post_dir,
            compression_inp=export_dir / f"{slug}.inp",
            topology_b31_inp=export_dir / f"{slug}_topology_b31.inp",
            meta_json=export_dir / f"{slug}_meta.json",
            nodes_csv=export_dir / f"{slug}_nodes.csv",
            beams_csv=export_dir / f"{slug}_beams.csv",
            wireframe_png=export_dir / f"{slug}_wireframe.png",
            odb=job_dir / f"{slug}.odb",
            stress_strain_csv=post_dir / f"{slug}_stress_strain.csv",
            stress_strain_raw_csv=post_dir / f"{slug}_stress_strain_raw.csv",
            stress_strain_png=post_dir / f"{slug}_stress_strain.png",
            yield_json=post_dir / f"{slug}_yield.json",
            case_manifest=export_dir / "case_manifest.json",
            active_manifest=OUTPUT_ROOT / "active_case.json",
        )
    return _build_case_paths(slug, stroke=stroke, layout=layout)


def ensure_case_dirs(paths: CasePaths) -> None:
    paths.export_dir.mkdir(parents=True, exist_ok=True)
    paths.job_dir.mkdir(parents=True, exist_ok=True)
    paths.post_dir.mkdir(parents=True, exist_ok=True)


def save_case_manifest(paths: CasePaths, *, extra: dict | None = None) -> None:
    payload = paths.to_dict()
    payload["job_name"] = paths.job_name
    payload["job_inp_name"] = paths.job_inp_name
    if extra:
        payload.update(extra)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    paths.case_manifest.write_text(text, encoding="utf-8")
    paths.active_manifest.write_text(text, encoding="utf-8")


def load_case_manifest(path: Path | str | None = None) -> dict:
    if path is None:
        path = OUTPUT_ROOT / "active_case.json"
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_active_case_paths() -> CasePaths:
    data = load_case_manifest()
    stroke: StrokeKind = data["stroke"]  # type: ignore[assignment]
    slug = data["slug"]
    if all(k in data for k in ("rod_kind", "angle_key", "load_dir")):
        layout = CaseLayout(
            rod_kind=data["rod_kind"],  # type: ignore[arg-type]
            angle_key=data["angle_key"],
            load_dir=data["load_dir"],  # type: ignore[arg-type]
        )
        return _build_case_paths(slug, stroke=stroke, layout=layout)
    return case_paths_for_slug(slug, stroke=stroke)
