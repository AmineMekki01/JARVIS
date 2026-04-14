# actions/reminder.py
from __future__ import annotations

import subprocess
import os
import sys
import platform
import plistlib
from datetime import datetime
from pathlib import Path


def _get_platform() -> str:
    """Returns the current platform: windows, macos, or linux."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _create_macos_reminder_script(task_name: str, message: str, temp_dir: str) -> str:
    """Creates a Python script for macOS notification."""
    script_path = os.path.join(temp_dir, f"{task_name}.py")
    safe_message = message.replace('"', '\\"').replace("'", "\\'")
    
    script_content = f'''#!/usr/bin/env python3
        import os
        import subprocess
        import sys

        # Play system sound
        subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], capture_output=True)

        # Show notification via osascript
        subprocess.run([
            "osascript", "-e",
            f'display notification "{safe_message}" with title "MARK Reminder" sound name "Glass"'
        ], capture_output=True)

        # Clean up self
        plist_path = os.path.expanduser(f"~/Library/LaunchAgents/{task_name}.plist")
        try:
            os.remove(plist_path)
        except:
            pass
        try:
            os.remove(__file__)
        except:
            pass
    '''
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script_content)
    os.chmod(script_path, 0o755)
    return script_path


def _create_launchd_plist(task_name: str, script_path: str, target_dt: datetime) -> str:
    """Creates a launchd plist for scheduling the reminder on macOS."""
    plist_dir = os.path.expanduser("~/Library/LaunchAgents")
    os.makedirs(plist_dir, exist_ok=True)
    
    plist_path = os.path.join(plist_dir, f"{task_name}.plist")
    
    plist_data = {
        "Label": task_name,
        "ProgramArguments": [sys.executable, script_path],
        "StartCalendarInterval": {
            "Year": target_dt.year,
            "Month": target_dt.month,
            "Day": target_dt.day,
            "Hour": target_dt.hour,
            "Minute": target_dt.minute,
        },
        "RunAtLoad": False,
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
    }
    
    with open(plist_path, "wb") as f:
        plistlib.dump(plist_data, f)
    
    return plist_path


def reminder(
    parameters: dict,
    response: str | None = None,
    player=None,
    session_memory=None
) -> str:
    """
    Sets a timed reminder using the platform's scheduler.
    - Windows: Task Scheduler (schtasks)
    - macOS: launchd
    - Linux: Limited support (background process)

    parameters:
        - date    (str) YYYY-MM-DD
        - time    (str) HH:MM
        - message (str)

    Returns a result string — Live API voices it automatically.
    No edge_speak needed.
    """

    date_str = parameters.get("date")
    time_str = parameters.get("time")
    message  = parameters.get("message", "Reminder")

    if not date_str or not time_str:
        return "I need both a date and a time to set a reminder."

    try:
        target_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")

        if target_dt <= datetime.now():
            return "That time is already in the past."

        task_name    = f"com.markxxxv.reminder.{target_dt.strftime('%Y%m%d%H%M')}"
        platform_os  = _get_platform()
        safe_message = message.replace('"', '').replace("'", "").strip()[:200]

        if platform_os == "macos":
            temp_dir = os.environ.get("TMPDIR", "/tmp")
            notify_script = _create_macos_reminder_script(task_name, safe_message, temp_dir)
            plist_path = _create_launchd_plist(task_name, notify_script, target_dt)
            
            result = subprocess.run(
                ["launchctl", "load", plist_path],
                capture_output=True, text=True
            )
            
            if result.returncode != 0:
                err = result.stderr.strip() or result.stdout.strip()
                print(f"[Reminder] ❌ launchctl failed: {err}")
                return "I couldn't schedule the reminder due to a system error."
            
            if player:
                player.write_log(f"[reminder] set for {date_str} {time_str}")
            
            return f"Reminder set for {target_dt.strftime('%B %d at %I:%M %p')}."

        elif platform_os == "windows":
            python_exe = sys.executable
            if python_exe.lower().endswith("python.exe"):
                pythonw = python_exe.replace("python.exe", "pythonw.exe")
                if os.path.exists(pythonw):
                    python_exe = pythonw

            temp_dir      = os.environ.get("TEMP", "C:\\Temp")
            notify_script = os.path.join(temp_dir, f"{task_name}.pyw")
            project_root  = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..")
            )

            script_code = f'''import sys, os, time
                sys.path.insert(0, r"{project_root}")

                try:
                    import winsound
                    for freq in [800, 1000, 1200]:
                        winsound.Beep(freq, 200)
                        time.sleep(0.1)
                except Exception:
                    pass

                try:
                    from win10toast import ToastNotifier
                    ToastNotifier().show_toast(
                        "MARK Reminder",
                        "{safe_message}",
                        duration=15,
                        threaded=False
                    )
                except Exception:
                    try:
                        import subprocess
                        subprocess.run(["msg", "*", "/TIME:30", "{safe_message}"], shell=True)
                    except Exception:
                        pass

                time.sleep(3)
                try:
                    os.remove(__file__)
                except Exception:
                    pass
                '''
            with open(notify_script, "w", encoding="utf-8") as f:
                f.write(script_code)

            xml_content = f'''
            <?xml version="1.0" encoding="UTF-16"?>
                <Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
                <RegistrationInfo>
                    <Description>MARK Reminder: {safe_message}</Description>
                </RegistrationInfo>
                <Triggers>
                    <TimeTrigger>
                    <StartBoundary>{target_dt.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>
                    <Enabled>true</Enabled>
                    </TimeTrigger>
                </Triggers>
                <Actions>
                    <Exec>
                    <Command>{python_exe}</Command>
                    <Arguments>"{notify_script}"</Arguments>
                    </Exec>
                </Actions>
                <Settings>
                    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
                    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
                    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
                    <StartWhenAvailable>true</StartWhenAvailable>
                    <WakeToRun>true</WakeToRun>
                    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
                    <Enabled>true</Enabled>
                </Settings>
                <Principals>
                    <Principal>
                    <LogonType>InteractiveToken</LogonType>
                    <RunLevel>LeastPrivilege</RunLevel>
                    </Principal>
                </Principals>
                </Task>
            '''

            xml_path = os.path.join(temp_dir, f"{task_name}.xml")
            with open(xml_path, "w", encoding="utf-16") as f:
                f.write(xml_content)

            result = subprocess.run(
                f'schtasks /Create /TN "{task_name}" /XML "{xml_path}" /F',
                shell=True, capture_output=True, text=True
            )

            try:
                os.remove(xml_path)
            except Exception:
                pass

            if result.returncode != 0:
                err = result.stderr.strip() or result.stdout.strip()
                print(f"[Reminder] ❌ schtasks failed: {err}")
                try:
                    os.remove(notify_script)
                except Exception:
                    pass
                return "I couldn't schedule the reminder due to a system error."

            if player:
                player.write_log(f"[reminder] set for {date_str} {time_str}")

            return f"Reminder set for {target_dt.strftime('%B %d at %I:%M %p')}."

        else:
            return "Reminder scheduling is not fully supported on Linux. Please use your system's calendar application."

    except ValueError:
        return "I couldn't understand that date or time format."

    except Exception as e:
        return f"Something went wrong while scheduling the reminder: {str(e)[:80]}"