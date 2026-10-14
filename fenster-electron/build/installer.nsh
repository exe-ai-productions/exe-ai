; The command on the path, Windows edition.
;
; The installer puts exe.cmd into a bin folder of its own beside the program
; and adds that folder to the user's PATH; the uninstaller takes both away
; again. The service folder itself stays off the PATH: it holds the
; program's libraries, and a library on the PATH is one every other program
; on the machine may pick up by mistake. exe.cmd hands everything to the
; client exe inside the service folder (deploy/exe-ai-terminal.spec).
;
; electron-builder reads this file by its name and splices the two macros
; into its installer script. The registry value and the broadcast are what
; Windows itself uses for the user's PATH: an open terminal keeps the PATH
; it was started with, a new one has the command.
;
; The PATH is somebody else's, and this file treats it that way. A value
; this installer cannot hold in one piece — longer than its strings, or not
; text — reads as empty; written back, that would erase it. So the value is
; only ever rewritten after it was read whole and the result still fits;
; otherwise it is left exactly as it is, and the command is simply not on
; the PATH.

!include "LogicLib.nsh"
!include "StrFunc.nsh"
!include "WinMessages.nsh"

; A string function exists only once it is declared, and a declared one that
; nobody calls is a warning — which this build treats as an error. Installer
; and uninstaller are compiled in two passes, each seeing only its own macro
; below, so each pass declares only what it calls.
!ifndef BUILD_UNINSTALLER
  ${StrStr}
!else
  ${UnStrRep}
!endif

; Reads the user's PATH into $R1. $R2 is "1" where that is the whole value —
; or where there is none yet, then $R1 is empty — and "" where a value is
; there that could not be read.
!macro exeUserPathRead
  StrCpy $R2 "1"
  ClearErrors
  ReadRegStr $R1 HKCU "Environment" "Path"
  ${If} ${Errors}
    StrCpy $R1 ""
    StrCpy $R3 0
    ${Do}
      ClearErrors
      EnumRegValue $R4 HKCU "Environment" $R3
      ${If} ${Errors}
      ${OrIf} $R4 == ""
        ${ExitDo}
      ${EndIf}
      ${If} $R4 == "Path"
        StrCpy $R2 ""
        ${ExitDo}
      ${EndIf}
      IntOp $R3 $R3 + 1
    ${Loop}
  ${EndIf}
!macroend

!macro exePathChanged
  SendMessage ${HWND_BROADCAST} ${WM_WININICHANGE} 0 "STR:Environment" /TIMEOUT=5000
!macroend

!macro customInstall
  Push $R0
  Push $R1
  Push $R2
  Push $R3
  Push $R4
  CreateDirectory "$INSTDIR\bin"
  FileOpen $R0 "$INSTDIR\bin\exe.cmd" w
  FileWrite $R0 '@"%~dp0..\resources\exe-ai-terminal\exe.exe" %*$\r$\n'
  FileClose $R0
  !insertmacro exeUserPathRead
  ; Room for the old value, the new folder and the separators around them.
  StrLen $R3 $R1
  StrLen $R4 "$INSTDIR\bin"
  IntOp $R3 $R3 + $R4
  IntOp $R3 $R3 + 3
  ${If} $R2 == "1"
  ${AndIf} $R3 < ${NSIS_MAX_STRLEN}
    ; Between separators, so that a folder whose name merely begins like
    ; this one does not count as this one.
    ${StrStr} $R4 ";$R1;" ";$INSTDIR\bin;"
    ${If} $R4 == ""
      ${If} $R1 == ""
        StrCpy $R1 "$INSTDIR\bin"
      ${Else}
        StrCpy $R1 "$R1;$INSTDIR\bin"
      ${EndIf}
      WriteRegExpandStr HKCU "Environment" "Path" "$R1"
      !insertmacro exePathChanged
    ${EndIf}
  ${EndIf}
  Pop $R4
  Pop $R3
  Pop $R2
  Pop $R1
  Pop $R0
!macroend

!macro customUnInstall
  Push $R1
  Push $R2
  Push $R3
  Push $R4
  ; An update runs the old uninstaller first and installs again right after:
  ; the PATH stays as it is then, only a real uninstall takes the folder out.
  ${IfNot} ${isUpdated}
    !insertmacro exeUserPathRead
    StrLen $R3 $R1
    IntOp $R3 $R3 + 3
    ${If} $R2 == "1"
    ${AndIf} $R1 != ""
    ${AndIf} $R3 < ${NSIS_MAX_STRLEN}
      ${UnStrRep} $R4 ";$R1;" ";$INSTDIR\bin;" ";"
      ${If} $R4 != ";$R1;"
        ; Without the two separators that were put around it.
        StrCpy $R4 $R4 "" 1
        StrCpy $R4 $R4 -1
        ${If} $R4 == ""
          DeleteRegValue HKCU "Environment" "Path"
        ${Else}
          WriteRegExpandStr HKCU "Environment" "Path" "$R4"
        ${EndIf}
        !insertmacro exePathChanged
      ${EndIf}
    ${EndIf}
  ${EndIf}
  Delete "$INSTDIR\bin\exe.cmd"
  RMDir "$INSTDIR\bin"
  Pop $R4
  Pop $R3
  Pop $R2
  Pop $R1
!macroend
