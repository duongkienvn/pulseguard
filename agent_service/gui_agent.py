"""
Status Monitor Agent - GUI Application
A standalone desktop application for monitoring system metrics.
Includes Platform-Agnostic Real-Time CPU Frequency Monitoring.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import json
import os
import sys
import platform
from pathlib import Path

import requests
import psutil

# --- Platform Specific Imports for CPU Frequency ---
if platform.system() == 'Windows':
    import ctypes
    from ctypes import byref, c_long, c_double, c_ulong, Structure, POINTER
    from ctypes.wintypes import DWORD, LPCSTR, LPCWSTR

# Configuration file path
CONFIG_DIR = Path.home() / ".statusmonitor"
CONFIG_FILE = CONFIG_DIR / "agent_config.json"


class CPUFrequencyMonitor:
    """
    Platform-agnostic CPU frequency monitor.
    Uses Windows PDH for accurate Turbo Boost readings on Windows.
    Uses /sys/fs on Linux.
    Falls back to psutil for macOS/others.
    """
    def __init__(self):
        self.os_type = platform.system()
        self.pdh_query = None
        self.pdh_counter = None
        
        if self.os_type == 'Windows':
            self._setup_windows_pdh()
    
    def _setup_windows_pdh(self):
        try:
            # Define Windows Structures locally to avoid polluting global namespace
            PDH_FMT_DOUBLE = 0x00000200
            ERROR_SUCCESS = 0x00000000

            self.pdh = ctypes.windll.pdh
            self.pdh_query = ctypes.c_void_p()
            self.pdh_counter = ctypes.c_void_p()
            
            if self.pdh.PdhOpenQueryW(None, 0, byref(self.pdh_query)) != ERROR_SUCCESS:
                return

            # Try English counter path first, then legacy
            counter_path = r"\Processor Information(_Total)\% Processor Performance"
            if self.pdh.PdhAddEnglishCounterW(self.pdh_query, counter_path, 0, byref(self.pdh_counter)) != ERROR_SUCCESS:
                counter_path_legacy = r"\Processor(_Total)\% Processor Performance"
                self.pdh.PdhAddEnglishCounterW(self.pdh_query, counter_path_legacy, 0, byref(self.pdh_counter))
                    
            self.pdh.PdhCollectQueryData(self.pdh_query)
            
        except Exception as e:
            print(f"PDH Init Error: {e}")
            self.pdh_query = None

    def get_frequency(self):
        """Returns current CPU frequency in MHz."""
        if self.os_type == 'Windows':
            return self._get_windows_real_freq()
        elif self.os_type == 'Linux':
            return self._get_linux_real_freq()
        else:
            # macOS and others
            return psutil.cpu_freq().current

    def _get_windows_real_freq(self):
        if not self.pdh_query:
            return psutil.cpu_freq().current

        base_freq = psutil.cpu_freq().max
        if base_freq == 0.0:
            base_freq = psutil.cpu_freq().current

        # Define structure for return value
        class PDH_FMT_COUNTERVALUE(Structure):
            _fields_ = [("CStatus", DWORD), ("doubleValue", c_double)]

        self.pdh.PdhCollectQueryData(self.pdh_query)
        ctype_type = DWORD(0)
        value = PDH_FMT_COUNTERVALUE()
        PDH_FMT_DOUBLE = 0x00000200
        
        res = self.pdh.PdhGetFormattedCounterValue(
            self.pdh_counter, PDH_FMT_DOUBLE, byref(ctype_type), byref(value)
        )
        
        if res != 0: # ERROR_SUCCESS
            return base_freq

        return base_freq * (value.doubleValue / 100.0)

    def _get_linux_real_freq(self):
        try:
            with open('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq', 'r') as f:
                return int(f.read().strip()) / 1000.0
        except:
            return psutil.cpu_freq().current


class MetricsCollector:
    """Collects system metrics."""
    
    _initialized = False
    _freq_monitor = None
    
    @classmethod
    def initialize(cls):
        """Initialize CPU monitoring baseline and Frequency Monitor."""
        if not cls._initialized:
            # Prime psutil blocking call
            psutil.cpu_percent(interval=None)
            
            # Initialize our custom frequency monitor
            cls._freq_monitor = CPUFrequencyMonitor()
            
            cls._initialized = True
    
    @classmethod
    def get_cpu_metrics(cls):
        # Non-blocking: uses time since last call for measurement
        # Primed during initialize() so first call is accurate
        usage = psutil.cpu_percent(interval=None)
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        
        # Get accurate frequency from our new monitor
        current_freq = cls._freq_monitor.get_frequency() if cls._freq_monitor else psutil.cpu_freq().current
        
        # Get psutil freq for min/max values
        psutil_freq = psutil.cpu_freq()
        freq_info = {
            "current": current_freq,
            "min": psutil_freq.min if psutil_freq else 0,
            "max": psutil_freq.max if psutil_freq else 0,
        }
        
        return {
            "usage_percent": usage,
            "per_core_usage": per_core,
            "freq": freq_info,
            "frequency_mhz": current_freq,  # Keep for backward compat with local display
            "count": psutil.cpu_count(logical=False),
            "count_logical": psutil.cpu_count(logical=True),
        }
    
    @staticmethod
    def get_memory_metrics():
        mem = psutil.virtual_memory()
        return {
            "total": mem.total,
            "available": mem.available,
            "used": mem.used,
            "used_percent": mem.percent,
        }
    
    @staticmethod
    def get_disk_metrics():
        partitions = []
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                partitions.append({
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent,
                })
            except PermissionError:
                continue
        return {"partitions": partitions}
    
    @staticmethod
    def get_network_metrics():
        net = psutil.net_io_counters()
        return {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        }
    
    @classmethod
    def collect_all(cls):
        return {
            "cpu": cls.get_cpu_metrics(),
            "memory": cls.get_memory_metrics(),
            "disk": cls.get_disk_metrics(),
            "network": cls.get_network_metrics(),
            "timestamp": time.time(),
        }


class ConfigManager:
    """Manages application configuration."""
    
    DEFAULT_CONFIG = {
        "server_url": "http://localhost:8001",
        "agent_token": "",
        "interval": 5,
        "auto_start": False,
    }
    
    @classmethod
    def load(cls):
        """Load configuration from file."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    return {**cls.DEFAULT_CONFIG, **config}
            except (json.JSONDecodeError, IOError):
                pass
        return cls.DEFAULT_CONFIG.copy()
    
    @classmethod
    def save(cls, config):
        """Save configuration to file."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)


class AgentGUI:
    """Main GUI Application."""
    
    def __init__(self, root):
        self.root = root
        self.root.title("Status Monitor Agent")
        self.root.geometry("500x600")
        self.root.resizable(False, False)
        
        # State
        self.config = ConfigManager.load()
        self.running = False
        self.agent_thread = None
        self.stop_event = threading.Event()
        
        # Metrics state
        self.metrics_sent = 0
        self.last_error = ""
        
        # Setup UI
        self.setup_ui()
        self.update_status_display()
        
        # Auto-start if configured
        if self.config.get("auto_start") and self.config.get("agent_token"):
            self.root.after(1000, self.start_agent)
        
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def setup_ui(self):
        """Setup the user interface."""
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.status_frame = ttk.Frame(self.notebook)
        self.settings_frame = ttk.Frame(self.notebook)
        
        self.notebook.add(self.status_frame, text="Status")
        self.notebook.add(self.settings_frame, text="Settings")
        
        self.setup_status_tab()
        self.setup_settings_tab()
    
    def setup_status_tab(self):
        """Setup the status tab."""
        header_frame = ttk.Frame(self.status_frame)
        header_frame.pack(fill=tk.X, padx=20, pady=20)
        
        ttk.Label(
            header_frame, 
            text="Status Monitor Agent", 
            font=("Segoe UI", 16, "bold")
        ).pack()
        
        self.status_frame_inner = ttk.LabelFrame(self.status_frame, text="Agent Status")
        self.status_frame_inner.pack(fill=tk.X, padx=20, pady=10)
        
        status_content = ttk.Frame(self.status_frame_inner)
        status_content.pack(fill=tk.X, padx=15, pady=15)
        
        status_row = ttk.Frame(status_content)
        status_row.pack(fill=tk.X)
        
        self.status_canvas = tk.Canvas(status_row, width=20, height=20, highlightthickness=0)
        self.status_canvas.pack(side=tk.LEFT)
        self.status_light = self.status_canvas.create_oval(2, 2, 18, 18, fill="gray", outline="darkgray")
        
        self.status_label = ttk.Label(status_row, text="Stopped", font=("Segoe UI", 12))
        self.status_label.pack(side=tk.LEFT, padx=10)
        
        ttk.Separator(status_content, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        
        metrics_row = ttk.Frame(status_content)
        metrics_row.pack(fill=tk.X)
        
        ttk.Label(metrics_row, text="Metrics Sent:").pack(side=tk.LEFT)
        self.metrics_count_label = ttk.Label(metrics_row, text="0", font=("Segoe UI", 10, "bold"))
        self.metrics_count_label.pack(side=tk.LEFT, padx=5)
        
        self.error_label = ttk.Label(status_content, text="", foreground="red", wraplength=400)
        self.error_label.pack(fill=tk.X, pady=(10, 0))
        
        metrics_frame = ttk.LabelFrame(self.status_frame, text="Current Metrics")
        metrics_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        self.metrics_text = tk.Text(metrics_frame, height=12, state=tk.DISABLED, font=("Consolas", 9))
        self.metrics_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        button_frame = ttk.Frame(self.status_frame)
        button_frame.pack(fill=tk.X, padx=20, pady=20)
        
        self.start_button = ttk.Button(
            button_frame, 
            text="Start Agent", 
            command=self.start_agent,
            style="Accent.TButton"
        )
        self.start_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
        
        self.stop_button = ttk.Button(
            button_frame, 
            text="Stop Agent", 
            command=self.stop_agent,
            state=tk.DISABLED
        )
        self.stop_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))
    
    def setup_settings_tab(self):
        """Setup the settings tab."""
        form_frame = ttk.Frame(self.settings_frame)
        form_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        ttk.Label(form_frame, text="Server URL:", font=("Segoe UI", 10)).pack(anchor=tk.W)
        self.server_url_var = tk.StringVar(value=self.config.get("server_url", ""))
        server_entry = ttk.Entry(form_frame, textvariable=self.server_url_var, width=50)
        server_entry.pack(fill=tk.X, pady=(5, 15))
        ttk.Label(
            form_frame, 
            text="The URL of the ingestion service (e.g., http://localhost:8001)",
            font=("Segoe UI", 8),
            foreground="gray"
        ).pack(anchor=tk.W)
        
        ttk.Separator(form_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)
        
        ttk.Label(form_frame, text="Agent Token:", font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(10, 0))
        self.token_var = tk.StringVar(value=self.config.get("agent_token", ""))
        
        token_frame = ttk.Frame(form_frame)
        token_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.token_entry = ttk.Entry(token_frame, textvariable=self.token_var, width=50, show="*")
        self.token_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.show_token_var = tk.BooleanVar(value=False)
        self.show_token_btn = ttk.Checkbutton(
            token_frame, 
            text="Show", 
            variable=self.show_token_var,
            command=self.toggle_token_visibility
        )
        self.show_token_btn.pack(side=tk.LEFT, padx=(10, 0))
        
        ttk.Label(
            form_frame, 
            text="Paste the token generated from the web dashboard when creating an agent",
            font=("Segoe UI", 8),
            foreground="gray",
            wraplength=400
        ).pack(anchor=tk.W, pady=(5, 0))
        
        ttk.Separator(form_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)
        
        ttk.Label(form_frame, text="Collection Interval (seconds):", font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(10, 0))
        
        interval_frame = ttk.Frame(form_frame)
        interval_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.interval_var = tk.IntVar(value=self.config.get("interval", 5))
        interval_spinbox = ttk.Spinbox(
            interval_frame, 
            from_=1, 
            to=60, 
            textvariable=self.interval_var,
            width=10
        )
        interval_spinbox.pack(side=tk.LEFT)
        
        ttk.Label(
            interval_frame, 
            text="seconds",
            font=("Segoe UI", 9)
        ).pack(side=tk.LEFT, padx=(5, 0))
        
        ttk.Separator(form_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)
        
        self.auto_start_var = tk.BooleanVar(value=self.config.get("auto_start", False))
        auto_start_check = ttk.Checkbutton(
            form_frame, 
            text="Auto-start agent when application opens",
            variable=self.auto_start_var
        )
        auto_start_check.pack(anchor=tk.W, pady=(10, 0))
        
        button_frame = ttk.Frame(form_frame)
        button_frame.pack(fill=tk.X, pady=(30, 0))
        
        ttk.Button(
            button_frame, 
            text="Test Connection", 
            command=self.test_connection
        ).pack(side=tk.LEFT)
        
        ttk.Button(
            button_frame, 
            text="Save Settings", 
            command=self.save_settings,
            style="Accent.TButton"
        ).pack(side=tk.RIGHT)
        
        info_frame = ttk.LabelFrame(self.settings_frame, text="How to get a token")
        info_frame.pack(fill=tk.X, padx=20, pady=(0, 20))
        
        info_text = """1. Log in to the Status Monitor web dashboard
2. Go to 'Agents' page
3. Click 'Add New Agent' and enter a name
4. Copy the generated token and paste it above
5. Save settings and start the agent"""
        
        ttk.Label(
            info_frame, 
            text=info_text,
            font=("Segoe UI", 9),
            justify=tk.LEFT
        ).pack(padx=15, pady=15, anchor=tk.W)
    
    def toggle_token_visibility(self):
        """Toggle token field visibility."""
        if self.show_token_var.get():
            self.token_entry.config(show="")
        else:
            self.token_entry.config(show="*")
    
    def update_status_display(self):
        """Update the status display."""
        if self.running:
            self.status_canvas.itemconfig(self.status_light, fill="green", outline="darkgreen")
            self.status_label.config(text="Running")
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
        else:
            self.status_canvas.itemconfig(self.status_light, fill="gray", outline="darkgray")
            self.status_label.config(text="Stopped")
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
        
        self.metrics_count_label.config(text=str(self.metrics_sent))
        self.error_label.config(text=self.last_error)
    
    def update_metrics_display(self, metrics):
        """Update the metrics text display."""
        self.metrics_text.config(state=tk.NORMAL)
        self.metrics_text.delete(1.0, tk.END)
        
        # ADDED: Display frequency in the text box
        text = f"""CPU Usage: {metrics['cpu']['usage_percent']:.1f}%
CPU Freq:  {metrics['cpu']['frequency_mhz']:.2f} MHz
CPU Cores: {metrics['cpu']['count']} physical, {metrics['cpu']['count_logical']} logical

Memory Usage: {metrics['memory']['used_percent']:.1f}%
Memory Total: {self.format_bytes(metrics['memory']['total'])}
Memory Available: {self.format_bytes(metrics['memory']['available'])}

Network Sent: {self.format_bytes(metrics['network']['bytes_sent'])}
Network Received: {self.format_bytes(metrics['network']['bytes_recv'])}

Disks:"""
        
        for partition in metrics['disk']['partitions']:
            text += f"\n  {partition['mountpoint']}: {partition['percent']:.1f}% used"
        
        self.metrics_text.insert(tk.END, text)
        self.metrics_text.config(state=tk.DISABLED)
    
    def format_bytes(self, bytes_val):
        """Format bytes to human readable."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024:
                return f"{bytes_val:.2f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.2f} PB"
    
    def save_settings(self):
        """Save settings to config file."""
        self.config = {
            "server_url": self.server_url_var.get().strip().rstrip('/'),
            "agent_token": self.token_var.get().strip(),
            "interval": self.interval_var.get(),
            "auto_start": self.auto_start_var.get(),
        }
        ConfigManager.save(self.config)
        messagebox.showinfo("Settings Saved", "Your settings have been saved successfully.")
    
    def test_connection(self):
        """Test connection to the server."""
        server_url = self.server_url_var.get().strip().rstrip('/')
        token = self.token_var.get().strip()
        
        if not server_url:
            messagebox.showerror("Error", "Please enter a server URL.")
            return
        
        if not token:
            messagebox.showerror("Error", "Please enter an agent token.")
            return
        
        try:
            # Try to send a test metric
            metrics = MetricsCollector.collect_all()
            response = requests.post(
                f"{server_url}/ingest",
                json=metrics,
                headers={"X-Agent-Token": token},
                timeout=10
            )
            
            if response.status_code == 200:
                messagebox.showinfo("Success", "Connection successful! The agent can reach the server.")
            elif response.status_code == 401:
                messagebox.showerror("Authentication Failed", "Invalid agent token. Please check your token.")
            elif response.status_code == 404:
                messagebox.showerror("Not Found", "The ingestion endpoint was not found. Check the server URL.")
            else:
                messagebox.showerror("Error", f"Server returned status code: {response.status_code}")
        except requests.exceptions.ConnectionError:
            messagebox.showerror("Connection Error", "Could not connect to the server. Check the URL and ensure the server is running.")
        except requests.exceptions.Timeout:
            messagebox.showerror("Timeout", "Connection timed out. The server may be slow or unreachable.")
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {str(e)}")
    
    def start_agent(self):
        """Start the metrics collection agent."""
        server_url = self.config.get("server_url", "").strip().rstrip('/')
        token = self.config.get("agent_token", "").strip()
        
        if not server_url or not token:
            messagebox.showerror(
                "Configuration Required", 
                "Please configure the server URL and agent token in the Settings tab."
            )
            self.notebook.select(1)  # Switch to settings tab
            return
        
        self.running = True
        self.stop_event.clear()
        self.last_error = ""
        self.update_status_display()
        
        # Start agent thread
        self.agent_thread = threading.Thread(target=self.agent_loop, daemon=True)
        self.agent_thread.start()
    
    def stop_agent(self):
        """Stop the metrics collection agent."""
        self.running = False
        self.stop_event.set()
        self.update_status_display()
    
    def agent_loop(self):
        """Main agent loop that collects and sends metrics."""
        server_url = self.config.get("server_url", "").rstrip('/')
        token = self.config.get("agent_token", "")
        interval = self.config.get("interval", 5)
        
        while not self.stop_event.is_set():
            try:
                # Collect metrics
                metrics = MetricsCollector.collect_all()
                
                # Update display
                self.root.after(0, lambda m=metrics: self.update_metrics_display(m))
                
                # Send to server
                response = requests.post(
                    f"{server_url}/ingest",
                    json=metrics,
                    headers={"X-Agent-Token": token},
                    timeout=10
                )
                
                if response.status_code == 200:
                    self.metrics_sent += 1
                    self.last_error = ""
                elif response.status_code == 401:
                    self.last_error = "Authentication failed - invalid token"
                else:
                    self.last_error = f"Server error: {response.status_code}"
                
                self.root.after(0, self.update_status_display)
                
            except requests.exceptions.ConnectionError:
                self.last_error = "Connection error - server unreachable"
                self.root.after(0, self.update_status_display)
            except Exception as e:
                self.last_error = f"Error: {str(e)}"
                self.root.after(0, self.update_status_display)
            
            # Wait for interval or stop event
            self.stop_event.wait(interval)
    
    def on_closing(self):
        """Handle window close event."""
        if self.running:
            if messagebox.askokcancel("Quit", "The agent is still running. Do you want to stop it and quit?"):
                self.stop_agent()
                self.root.destroy()
        else:
            self.root.destroy()


def main():
    """Main entry point."""
    # Initialize CPU monitoring baseline before any readings
    MetricsCollector.initialize()
    
    root = tk.Tk()
    
    # Try to use a nicer theme
    try:
        root.tk.call("source", "azure.tcl")
        root.tk.call("set_theme", "light")
    except:
        # Fall back to default theme
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    
    # Configure custom style
    style = ttk.Style()
    style.configure("Accent.TButton", font=("Segoe UI", 10))
    
    app = AgentGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()