; 蜂元虚拟工厂 NSIS 安装包的补充脚本（electron-builder 的 nsis.include）。
; 卸载时多一页"卸载选项"：默认保留数据目录（%LOCALAPPDATA%\HoneyVF：工厂、作业、PLC 程序、设置），勾选"同时删除数据"才删。
; 静默卸载（/S）和自动更新时卸载旧版本都不会删数据。另外卸载时删掉运行时注册的 vfactory:// 链接。
; 这个文件要存成带 BOM 的 UTF-8（NSIS 才认中文）。

!ifdef BUILD_UNINSTALLER
  !include nsDialogs.nsh
  Var vfDelData
  Var vfDelCheck

  !macro customUnWelcomePage
    !insertmacro MUI_UNPAGE_WELCOME
    UninstPage custom un.vfDataPageShow un.vfDataPageLeave

    Function un.vfDataPageShow
      !insertmacro MUI_HEADER_TEXT "卸载选项" "你的数据默认保留，重新安装后可以接着用"
      nsDialogs::Create 1018
      Pop $0
      ${NSD_CreateLabel} 0 0 100% 48u "程序文件会被删除。你的工厂、作业、PLC 程序、课程进度和设置保存在：$\r$\n$LOCALAPPDATA\HoneyVF$\r$\n默认保留。"
      Pop $0
      ${NSD_CreateCheckbox} 0 60u 100% 14u "同时删除数据（删了不能恢复）"
      Pop $vfDelCheck
      ${NSD_SetState} $vfDelCheck $vfDelData
      nsDialogs::Show
    FunctionEnd

    Function un.vfDataPageLeave
      ${NSD_GetState} $vfDelCheck $vfDelData
    FunctionEnd
  !macroend

  !macro customUnInstall
    ${ifNot} ${isUpdated}
      DeleteRegKey HKCU "Software\Classes\vfactory"
      RMDir /r "$LOCALAPPDATA\honeyvf-desktop-updater"       ; 自动更新下载的安装包缓存（electron-updater，按 package.json 的 name 起名）
      ; electron-builder 删了 HoneyVF.Homework / HoneyVF.Plant，但 .vfhw / .vfplant 的默认值还指着它们：清掉（别的程序的 OpenWithProgids 不动）
      ReadRegStr $0 HKCU "Software\Classes\.vfhw" ""
      ${if} $0 == "HoneyVF.Homework"
        DeleteRegValue HKCU "Software\Classes\.vfhw" ""
        DeleteRegKey /ifempty HKCU "Software\Classes\.vfhw\OpenWithProgids"
        DeleteRegKey /ifempty HKCU "Software\Classes\.vfhw"
      ${endif}
      ReadRegStr $0 HKCU "Software\Classes\.vfplant" ""
      ${if} $0 == "HoneyVF.Plant"
        DeleteRegValue HKCU "Software\Classes\.vfplant" ""
        DeleteRegKey /ifempty HKCU "Software\Classes\.vfplant\OpenWithProgids"
        DeleteRegKey /ifempty HKCU "Software\Classes\.vfplant"
      ${endif}
      ${if} $vfDelData == ${BST_CHECKED}
        RMDir /r "$LOCALAPPDATA\HoneyVF"
      ${endif}
    ${endif}
  !macroend
!endif
