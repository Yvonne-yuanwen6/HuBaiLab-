"""Run Abaqus/CAE mesh locally (Windows/Linux) or on remote Linux server."""

from __future__ import annotations

import os
import subprocess
import sys


def _repo_rel(path: str, root: str) -> str:
    return os.path.relpath(path, root).replace("\\", "/")


def _run_local_cae_mesh(
    root: str,
    step_path: str,
    out_inp: str,
    seed_mm: float,
    part_name: str,
    mesh_mode: str = "tet",
    *,
    mesh_quality: str = "lattice_contact",
    rod_diameter_mm: float = 2.0,
    rods_per_diameter: float = 3.0,
    virtual_topology: bool = False,
    element_type: str = "C3D4",
) -> None:
    if sys.platform == "win32":
        pilot_ps1 = os.path.join(root, "scripts", "run_abaqus_cae_hex_mesh_pilot.ps1")
        cmd = [
            "powershell",
            "-NoProfile",
            "-File",
            pilot_ps1,
            "-MeshMode",
            mesh_mode,
            "-SeedMm",
            str(seed_mm),
            "-StepPath",
            step_path,
            "-OutInp",
            out_inp,
            "-PartName",
            part_name,
        ]
    else:
        mesh_sh = os.path.join(root, "scripts", "linux", "run_abaqus_cae_mesh.sh")
        cmd = [
            "bash",
            mesh_sh,
            "--step",
            _repo_rel(step_path, root),
            "--out",
            _repo_rel(out_inp, root),
            "--seed",
            str(seed_mm),
            "--mesh-mode",
            mesh_mode,
            "--mesh-quality",
            mesh_quality,
            "--rod-diameter",
            str(rod_diameter_mm),
            "--rods-per-diameter",
            str(rods_per_diameter),
            "--part-name",
            part_name,
            "--element-type",
            element_type,
        ]
        if virtual_topology:
            cmd.append("--virtual-topology")
    print(f"  Running: {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=root, check=True)


def _run_remote_cae_mesh(
    root: str,
    remote_host: str,
    remote_root: str,
    step_path: str,
    out_inp: str,
    seed_mm: float,
    part_name: str,
    mesh_mode: str = "tet",
    *,
    mesh_quality: str = "lattice_contact",
    rod_diameter_mm: float = 2.0,
    rods_per_diameter: float = 3.0,
    virtual_topology: bool = False,
    element_type: str = "C3D4",
) -> None:
    rel_step = _repo_rel(step_path, root)
    rel_out = _repo_rel(out_inp, root)
    remote_step = f"{remote_root}/{rel_step}"
    remote_out = f"{remote_root}/{rel_out}"
    remote_export_dir = os.path.dirname(remote_out)

    ssh_base = ["ssh", "-o", "BatchMode=yes", remote_host]
    scp_base = ["scp", "-o", "BatchMode=yes"]

    print(f"  CAE mesh on server: {remote_host}", flush=True)
    print(f"  remote STEP: {remote_step}", flush=True)
    print(f"  remote OUT:  {remote_out}", flush=True)

    subprocess.run(
        ssh_base + [f"mkdir -p '{remote_export_dir}'"],
        check=True,
    )

    step_check = subprocess.run(
        ssh_base + [f"test -f '{remote_step}'"],
        capture_output=True,
    )
    if step_check.returncode != 0:
        print(f"  scp STEP -> server ({rel_step})", flush=True)
        remote_step_dir = os.path.dirname(remote_step).replace("\\", "/")
        subprocess.run(
            ssh_base + [f"mkdir -p '{remote_step_dir}'"],
            check=True,
        )
        subprocess.run(
            scp_base + [step_path, f"{remote_host}:{remote_step}"],
            check=True,
        )

    remote_cmd = (
        f"cd '{remote_root}' && "
        f"bash scripts/linux/run_abaqus_cae_mesh.sh "
        f"--step '{rel_step}' --out '{rel_out}' "
        f"--seed {seed_mm} --mesh-mode {mesh_mode} "
        f"--mesh-quality {mesh_quality} "
        f"--rod-diameter {rod_diameter_mm} --rods-per-diameter {rods_per_diameter} "
        f"--part-name '{part_name}' --element-type {element_type}"
    )
    if virtual_topology:
        remote_cmd += " --virtual-topology"
    subprocess.run(ssh_base + [remote_cmd], check=True)

    os.makedirs(os.path.dirname(out_inp), exist_ok=True)
    subprocess.run(
        scp_base + [f"{remote_host}:{remote_out}", out_inp],
        check=True,
    )


def run_cae_mesh(
    root: str,
    step_path: str,
    out_inp: str,
    seed_mm: float,
    part_name: str,
    *,
    mesh_on_server: bool = False,
    remote_host: str = "",
    remote_root: str = "",
    mesh_mode: str = "tet",
    mesh_quality: str = "lattice_contact",
    rod_diameter_mm: float = 2.0,
    rods_per_diameter: float = 3.0,
    virtual_topology: bool = False,
    element_type: str = "C3D4",
) -> str:
    """Run CAE mesh; returns 'server' or 'local'."""
    if mesh_on_server:
        if not remote_host or not remote_root:
            raise ValueError("mesh-on-server requires --remote-host and --remote-root")
        _run_remote_cae_mesh(
            root,
            remote_host,
            remote_root,
            step_path,
            out_inp,
            seed_mm,
            part_name,
            mesh_mode=mesh_mode,
            mesh_quality=mesh_quality,
            rod_diameter_mm=rod_diameter_mm,
            rods_per_diameter=rods_per_diameter,
            virtual_topology=virtual_topology,
            element_type=element_type,
        )
        return "server"
    _run_local_cae_mesh(
        root,
        step_path,
        out_inp,
        seed_mm,
        part_name,
        mesh_mode=mesh_mode,
        mesh_quality=mesh_quality,
        rod_diameter_mm=rod_diameter_mm,
        rods_per_diameter=rods_per_diameter,
        virtual_topology=virtual_topology,
        element_type=element_type,
    )
    return "local"
