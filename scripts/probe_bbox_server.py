from src.export.paper_box_array_fuse import _count_seed_volumes, fuse_paper_box_unitcell_seed_to_one
import gmsh
import os
from src.paths import CAD_ROOT

pairs = [
    ("Q1 8-body", "output/cad/_unitcell_paper_box_cut/unitcell_sfbls_af2q1_paper_box.step"),
    ("Q15 1-body", "output/cad/_unitcell_paper_box_cut/unitcell_sfbls_af2q1p5_paper_box.step"),
]
merged = os.path.join(str(CAD_ROOT), "_unitcell_paper_box_cut", "unitcell_sfbls_af2q1_merged_1vol.step")
fuse_paper_box_unitcell_seed_to_one(pairs[0][1], merged, progress_label="probe-merge")
pairs.append(("Q1 merged", merged))

for label, path in pairs:
    print(label, "vols=", _count_seed_volumes(path))
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("t")
    gmsh.model.occ.importShapes(path)
    gmsh.model.occ.synchronize()
    bb = gmsh.model.getBoundingBox(-1, -1)
    print("  bbox", [round(bb[i], 1) for i in range(6)], "vols", len(gmsh.model.getEntities(3)))
    gmsh.finalize()
