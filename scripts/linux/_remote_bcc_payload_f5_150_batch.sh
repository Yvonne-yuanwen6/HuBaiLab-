#!/usr/bin/env bash
# BCC wrapper — kept for backward compatibility.
export Q=0
export VARIANT_PREFIX=comsol_fig321_bcc_444
export VARIANT_LABEL=BCC
export CAD=output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step
export OUT_DIR=output/comsol_jobs/bcc_payload_composite
export OVERLAY_SLUG=bcc_p1_f5_150_payload_overlay
export BATCH_LOG=output/logs/bcc_payload_f5_150_batch.log
export PAPER_OVERLAY=bcc
exec "$(dirname "$0")/_remote_payload_f5_150_batch.sh"
