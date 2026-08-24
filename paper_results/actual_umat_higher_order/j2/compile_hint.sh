#!/usr/bin/env bash
set -euo pipefail
OBJDIR=${OBJDIR:-.}
gfortran -c -ffree-form -ffree-line-length-none master_parameters.f90 -J"$OBJDIR" -o "$OBJDIR/master_parameters.o"
gfortran -c -ffree-form -ffree-line-length-none -I"$OBJDIR" real_utils.f90 -J"$OBJDIR" -o "$OBJDIR/real_utils.o"
gfortran -c -ffree-form -ffree-line-length-none -I"$OBJDIR" otim6n4.f90 -J"$OBJDIR" -o "$OBJDIR/otim6n4.o"
gfortran -c -ffixed-form -ffixed-line-length-none -I"$OBJDIR" j2_props_oti.f -J"$OBJDIR" -o "$OBJDIR/transformed_umat.o"
