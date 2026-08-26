FC      ?= gfortran
FCFLAGS ?= -O1 -std=legacy -ffree-line-length-none -fno-align-commons

.PHONY: all clean
all: ps_driver

master_parameters.o: master_parameters.f90
	$(FC) $(FCFLAGS) -c $<

real_utils.o: real_utils.f90 master_parameters.o
	$(FC) $(FCFLAGS) -c $<

otim4n1.o: otim4n1.f90 master_parameters.o real_utils.o
	$(FC) $(FCFLAGS) -c $<

oti_intrinsics.o: oti_intrinsics.f90 otim4n1.o master_parameters.o
	$(FC) $(FCFLAGS) -c $<

umat_oti_lifted.o: umat_oti_lifted.f90 otim4n1.o oti_intrinsics.o
	$(FC) $(FCFLAGS) -c $<

ps_driver.o: ps_driver.f90 umat_oti_lifted.o otim4n1.o
	$(FC) $(FCFLAGS) -c $<

abaqus_stubs.o: abaqus_stubs.f90
	$(FC) $(FCFLAGS) -c $<

ps_driver: master_parameters.o real_utils.o otim4n1.o oti_intrinsics.o umat_oti_lifted.o abaqus_stubs.o ps_driver.o
	$(FC) $(FCFLAGS) $^ -o $@

clean:
	rm -f *.o *.mod ps_driver *.csv
