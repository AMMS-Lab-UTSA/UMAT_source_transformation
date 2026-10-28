! Material-point driver for the R1 verification (Ada, 2026-10-27).
! Written independently of UMAT-OTI's own drivers. Links against either the
! untransformed R1 UMAT or the UMAT-OTI tangent build (same interface).
!
! Input file r1_in.txt (list-directed):
!   nprops / props(1:nprops) / nstatv / ninc / dstran(1:6) per increment
!   mode: 0 = path only; 1 = also strain FD at every increment;
!         2 = also PROPS FD over the whole history
!   nsteps / steps(1:nsteps)
! For mode 1 each step h is an absolute strain step; the FD column j is
!   (S(dE + h e_j) - S(dE - h e_j)) / (2h) from the SAME incoming state.
! For mode 2 each step is relative: h_k = step*|PROPS(k)|; the whole path is
!   re-run with PROPS(k) +- h_k and every increment's STRESS and STATEV
!   differenced (total derivative along the history).
! Output r1_out.txt: one record per line, tagged.
program r1_driver
  implicit none
  integer, parameter :: ntens = 6
  integer :: nprops, nstatv, ninc, mode, nsteps, i, j, k, inc, s
  double precision, allocatable :: props(:), path(:,:), steps(:)
  double precision, allocatable :: statev(:), sv0(:), svp(:), svm(:), pp(:)
  double precision, allocatable :: hist_p(:,:,:), hist_m(:,:,:)
  double precision :: stress(ntens), ddsdde(ntens,ntens), s0(ntens)
  double precision :: sp(ntens), sm(ntens), dd(ntens,ntens), de(ntens)
  double precision :: dscr(ntens,ntens)  ! scratch: UMAT's own DDSDDE output
  double precision :: stran(ntens), pnewdt, h
  integer :: u, w

  open(newunit=u, file='r1_in.txt', status='old')
  read(u,*) nprops
  allocate(props(nprops), pp(nprops))
  read(u,*) props
  read(u,*) nstatv
  read(u,*) ninc
  allocate(path(ntens,ninc))
  do inc = 1, ninc
    read(u,*) path(:,inc)
  end do
  read(u,*) mode
  read(u,*) nsteps
  allocate(steps(nsteps))
  read(u,*) steps
  close(u)
  allocate(statev(nstatv), sv0(nstatv), svp(nstatv), svm(nstatv))

  open(newunit=w, file='r1_out.txt', status='replace')
  write(w,'(A,3I6)') 'HEADER', ninc, nstatv, nsteps
  stress = 0d0; statev = 0d0; stran = 0d0
  do inc = 1, ninc
    s0 = stress; sv0 = statev
    call one(props, s0, sv0, path(:,inc), stran, inc, stress, statev, ddsdde, pnewdt)
    write(w,'(A,I6,6ES26.17E3)') 'STRESS', inc, stress
    write(w,'(A,I6,*(ES26.17E3))') 'STATEV', inc, statev
    write(w,'(A,I6,36ES26.17E3)') 'DDSDDE', inc, ((ddsdde(i,j), j=1,ntens), i=1,ntens)
    write(w,'(A,I6,ES26.17E3)') 'PNEWDT', inc, pnewdt
    if (mode == 1) then
      do s = 1, nsteps
        h = steps(s)
        do j = 1, ntens
          de = path(:,inc); de(j) = de(j) + h
          call one(props, s0, sv0, de, stran, inc, sp, svp, dscr, pnewdt)
          de = path(:,inc); de(j) = de(j) - h
          call one(props, s0, sv0, de, stran, inc, sm, svm, dscr, pnewdt)
          dd(:,j) = (sp - sm)/(2d0*h)
        end do
        write(w,'(A,I6,ES12.4,36ES26.17E3)') 'FDTAN', inc, h, &
          ((dd(i,j), j=1,ntens), i=1,ntens)
      end do
    end if
    stran = stran + path(:,inc)
  end do

  if (mode == 2) then
    allocate(hist_p(ntens+nstatv,ninc,2), hist_m(ntens+nstatv,ninc,2))
    do s = 1, nsteps
      do k = 1, nprops
        h = steps(s)*max(abs(props(k)), 1d-30)
        pp = props; pp(k) = pp(k) + h
        call run_path(pp, hist_p(:,:,1))
        pp = props; pp(k) = pp(k) - h
        call run_path(pp, hist_m(:,:,1))
        do inc = 1, ninc
          write(w,'(A,I6,I4,ES12.4,*(ES26.17E3))') 'FDPROP', inc, k, steps(s), &
            (hist_p(:,inc,1) - hist_m(:,inc,1))/(2d0*h)
        end do
      end do
    end do
  end if
  close(w)

contains

  subroutine run_path(pv, hist)
    double precision, intent(in) :: pv(:)
    double precision, intent(out) :: hist(:,:)
    double precision :: st(ntens), sv(nstatv), st0(ntens), sv00(nstatv)
    double precision :: dl(ntens,ntens), stn(ntens), pn
    integer :: n
    st = 0d0; sv = 0d0; stn = 0d0
    do n = 1, ninc
      st0 = st; sv00 = sv
      call one(pv, st0, sv00, path(:,n), stn, n, st, sv, dl, pn)
      hist(1:ntens,n) = st
      hist(ntens+1:ntens+nstatv,n) = sv
      stn = stn + path(:,n)
    end do
  end subroutine run_path

  subroutine one(pv, sin, svin, dstran, stran_in, kinc, sout, svout, dds, pnew)
    double precision, intent(in) :: pv(:), sin(ntens), svin(:), dstran(ntens)
    double precision, intent(in) :: stran_in(ntens)
    integer, intent(in) :: kinc
    double precision, intent(out) :: sout(ntens), svout(:), dds(ntens,ntens), pnew
    double precision :: sse, spd, scd, rpl, ddsddt(ntens), drplde(ntens), drpldt
    double precision :: time(2), dtime, temp, dtemp, predef(1), dpred(1)
    double precision :: coords(3), drot(3,3), celent, dfgrd0(3,3), dfgrd1(3,3)
    double precision :: pl(size(pv)), dst(ntens), stn(ntens)
    character(len=80) :: cmname
    integer :: ndi, nshr, nt, nsv, np, noel, npt, layer, kspt, kstep, ki
    sout = sin; svout = svin; dds = 0d0; pnew = 1d0
    sse = 0d0; spd = 0d0; scd = 0d0; rpl = 0d0; ddsddt = 0d0; drplde = 0d0
    drpldt = 0d0; time = 0d0; dtime = 1d0; temp = 0d0; dtemp = 0d0
    predef = 0d0; dpred = 0d0; coords = 0d0; celent = 1d0
    drot = 0d0; dfgrd0 = 0d0; dfgrd1 = 0d0
    drot(1,1) = 1d0; drot(2,2) = 1d0; drot(3,3) = 1d0
    dfgrd0 = drot; dfgrd1 = drot
    cmname = 'R1'
    ndi = 3; nshr = 3; nt = ntens; nsv = size(svin); np = size(pv)
    noel = 1; npt = 1; layer = 1; kspt = 1; kstep = 1; ki = kinc
    pl = pv; dst = dstran; stn = stran_in
    call umat(sout, svout, dds, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
      stn, dst, time, dtime, temp, dtemp, predef, dpred, cmname, &
      ndi, nshr, nt, nsv, pl, np, coords, drot, pnew, celent, dfgrd0, &
      dfgrd1, noel, npt, layer, kspt, kstep, ki)
  end subroutine one

end program r1_driver
