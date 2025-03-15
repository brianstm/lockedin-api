import psutil
import time
import json
from datetime import datetime, timedelta
import threading
import os
import platform
import subprocess

if platform.system() == 'Darwin':
    import Quartz
    import AppKit
    import Foundation
elif platform.system() == 'Windows':
    import win32gui
    import win32process
elif platform.system() == 'Linux':
    import Xlib
    import Xlib.display
    import Xlib.protocol.event

class ApplicationTracker:
    def __init__(self, log_file='app_usage.json', interval=1):
        self.interval = interval
        self.is_tracking = False
        self.current_app = None
        self.current_app_start_time = None
        self.log_file = log_file
        self.lock = threading.Lock()
        
        self.app_logs = self.load_logs()

    def load_logs(self):
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r') as f:
                    return json.load(f)
            return []
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def save_logs(self):
        with open(self.log_file, 'w') as f:
            json.dump(self.app_logs, f, indent=4, default=str)

    def _get_chrome_tab_mac(self):
        script = '''
        tell application "Google Chrome"
            set currentTab to active tab of front window
            return URL of currentTab
        end tell
        '''
        try:
            process = subprocess.Popen(['osascript', '-e', script], 
                                       stdout=subprocess.PIPE, 
                                       stderr=subprocess.PIPE, 
                                       universal_newlines=True)
            stdout, stderr = process.communicate(timeout=2)
            
            if stdout.strip():
                return stdout.strip()
            return None
        except Exception:
            return None

    def get_active_window(self):
        try:
            system = platform.system()
            
            if system == 'Darwin':
                return self._get_active_window_mac()
            elif system == 'Windows':
                return self._get_active_window_windows()
            elif system == 'Linux':
                return self._get_active_window_linux()
            else:
                print(f"Unsupported OS: {system}")
                return None, None
        
        except Exception as e:
            print(f"Error getting active window: {e}")
            return None, None

    def _get_active_window_mac(self):
        workspace = AppKit.NSWorkspace.sharedWorkspace()
        front_app = workspace.activeApplication()
        app_name = front_app.get('NSApplicationName', 'Unknown')
        
        if app_name == 'Google Chrome':
            current_tab = self._get_chrome_tab_mac()
            if current_tab:
                return app_name, f"Chrome - {current_tab}"
        
        for window in Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID
        ):
            window_owner = window.get('kCGWindowOwnerName', '')
            window_name = window.get('kCGWindowName', '')
            
            if window_owner == app_name and window_name:
                return app_name, f"{app_name} - {window_name}"
        
        return app_name, app_name

    def _get_active_window_windows(self):
        try:
            hwnd = win32gui.GetForegroundWindow()
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            process = psutil.Process(pid)
            
            window_title = win32gui.GetWindowText(hwnd)
            return process.name(), window_title
        except Exception:
            return None, None

    def _get_active_window_linux(self):
        try:
            display = Xlib.display.Display()
            window = display.get_input_focus().focus
            
            window_class = window.get_wm_class()[1] if window.get_wm_class() else 'Unknown'
            window_name = window.get_full_property(display.get_atom('_NET_WM_NAME'), 0).value.decode() if window else 'Untitled'
            
            return window_class, f"{window_class} - {window_name}"
        except Exception:
            return None, None

    def track_applications(self):
        while self.is_tracking:
            current_window = self.get_active_window()
            
            if current_window[0] is not None:
                with self.lock:
                    if (self.current_app is None or 
                        self.current_app[0] != current_window[0] or 
                        self.current_app[1] != current_window[1]):
                        
                        if self.current_app:
                            end_time = datetime.now()
                            duration = int((end_time - self.current_app_start_time).total_seconds())
                            
                            log_entry = {
                                'app_name': self.current_app[0],
                                'window_title': self.current_app[1],
                                'start_time': str(self.current_app_start_time),
                                'end_time': str(end_time),
                                'duration': duration
                            }
                            
                            self.app_logs.append(log_entry)
                            self.save_logs()
                        
                        self.current_app = current_window
                        self.current_app_start_time = datetime.now()
            
            time.sleep(self.interval)

    def start_tracking(self):
        if not self.is_tracking:
            self.is_tracking = True
            self.tracking_thread = threading.Thread(target=self.track_applications)
            self.tracking_thread.start()
            print("Application tracking started...")

    def stop_tracking(self):
        self.is_tracking = False
        if hasattr(self, 'tracking_thread'):
            self.tracking_thread.join()
        
        if self.current_app:
            end_time = datetime.now()
            duration = int((end_time - self.current_app_start_time).total_seconds())
            
            log_entry = {
                'app_name': self.current_app[0],
                'window_title': self.current_app[1],
                'start_time': str(self.current_app_start_time),
                'end_time': str(end_time),
                'duration': duration
            }
            
            self.app_logs.append(log_entry)
            self.save_logs()

    def get_daily_report(self):
        today = datetime.now().date()
        daily_logs = [
            log for log in self.app_logs 
            if datetime.strptime(log['start_time'], '%Y-%m-%d %H:%M:%S.%f').date() == today
        ]
        
        usage_report = {}
        for log in daily_logs:
            app_name = log['app_name']
            window_title = log["window_title"]
            duration = log['duration']
            usage_report[app_name + ": " + window_title] = usage_report.get(app_name, 0) + duration
        
        return usage_report

def main():
    tracker = ApplicationTracker()
    
    try:
        tracker.start_tracking()
        
        time.sleep(60)
        
        tracker.stop_tracking()
        
        print("Daily App Usage Report:")
        report = tracker.get_daily_report()
        for app, duration in report.items():
            print(f"{app}: {timedelta(seconds=duration)}")
    
    finally:
        pass

if __name__ == "__main__":
    main()