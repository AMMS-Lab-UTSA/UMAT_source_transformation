#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
OBJDIR=${OBJDIR:-.}
mkdir -p -- "$OBJDIR"
gfortran -c -ffree-form -ffree-line-length-none master_parameters.f90 -J"$OBJDIR" -o "$OBJDIR/master_parameters.o"
gfortran -c -ffree-form -ffree-line-length-none -I"$OBJDIR" real_utils.f90 -J"$OBJDIR" -o "$OBJDIR/real_utils.o"
gfortran -c -ffree-form -ffree-line-length-none -I"$OBJDIR" otim6n1.f90 -J"$OBJDIR" -o "$OBJDIR/otim6n1.o"
gfortran -c -ffree-form -ffree-line-length-none -I"$OBJDIR" oti_intrinsics.f90 -J"$OBJDIR" -o "$OBJDIR/oti_intrinsics.o"
gfortran -c -ffixed-form -ffixed-line-length-none -I. -I"$OBJDIR" "umat_j2_voce_resolved_oti.f" -J"$OBJDIR" -o "$OBJDIR/transformed_umat.o"
