subroutine rotsig_oti(s, r, output, lstr, ndi, nshr)
    use otim3n1, OTI_HELPER_DP => DP
    use oti_intrinsics
    implicit type(ONUMM3N1) (a-h,o-z)
    implicit integer (i-n)
    type(ONUMM3N1) :: S(NDI+NSHR), R(3,3), OUTPUT(NDI+NSHR)
    type(ONUMM3N1) :: T(3,3), TR(3,3)
    real(8) :: halfsh
    HALFSH = 1.0D0
    IF (LSTR .EQ. 2) HALFSH = 0.5D0
    DO I = 1, 3
    DO J = 1, 3
    T(I,J) = 0.0D0
    END DO
    END DO
    DO I = 1, NDI
    T(I,I) = S(I)
    END DO
    IF (NSHR .GE. 1) THEN
    T(1,2) = S(NDI+1)*HALFSH
    T(2,1) = T(1,2)
    END IF
    IF (NSHR .GE. 2) THEN
    T(1,3) = S(NDI+2)*HALFSH
    T(3,1) = T(1,3)
    END IF
    IF (NSHR .GE. 3) THEN
    T(2,3) = S(NDI+3)*HALFSH
    T(3,2) = T(2,3)
    END IF
    DO I = 1, 3
    DO J = 1, 3
    TR(I,J) = 0.0D0
    DO K = 1, 3
    DO L = 1, 3
    TR(I,J) = TR(I,J) + R(I,K)*T(K,L)*R(J,L)
    END DO
    END DO
    END DO
    END DO
    DO I = 1, NDI
    OUTPUT(I) = TR(I,I)
    END DO
    IF (NSHR .GE. 1) OUTPUT(NDI+1) = TR(1,2)/HALFSH
    IF (NSHR .GE. 2) OUTPUT(NDI+2) = TR(1,3)/HALFSH
    IF (NSHR .GE. 3) OUTPUT(NDI+3) = TR(2,3)/HALFSH
    RETURN
end subroutine rotsig_oti
