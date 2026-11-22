#Requires AutoHotkey v2.0
#SingleInstance Force

; Global hotkey for the Voice Assistant one-command launcher.
; The backend is kept warm by a watchdog, so Ctrl + ; only toggles the panel.
; voice.ps1 holds a named mutex, so rapid repeat presses are rejected there;
; there is no client-side delay that could swallow a legitimate second press.

; Keep the backend healthy and the browser profile warm from login onward.
; The PowerShell script holds its own watchdog mutex, so only one copy runs.
Run 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\GEN_AI\PrepMate\VoiceAssistant\scripts\voice.ps1" -Watch', , "Hide"

ToggleVoice(*) {
    Run 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\GEN_AI\PrepMate\VoiceAssistant\scripts\voice.ps1" -Toggle', , "Hide"
}

Hotkey "^;", ToggleVoice

A_IconTip := "Voice Assistant"
