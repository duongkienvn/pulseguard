import psutil
import time

def get_cpu_metrics():
    try:
        load_avg = psutil.getloadavg() if hasattr(psutil, "getloadavg") else []
    except Exception:
        load_avg = []
    
    # Use interval=1 for accurate reading (shorter intervals can be unreliable)
    usage = psutil.cpu_percent(interval=1)
    per_core = psutil.cpu_percent(interval=None, percpu=True)  # Already measured after the above call
        
    return {
        "usage_percent": usage,
        "per_core_usage": per_core,
        "freq": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else {},
        "load_avg": load_avg
    }

def get_memory_metrics():
    vm = psutil.virtual_memory()
    return {
        "total": vm.total,
        "available": vm.available,
        "used_percent": vm.percent
    }

def get_disk_metrics():
    partitions = []
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            partitions.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent
            })
        except PermissionError:
            continue
            
    io = psutil.disk_io_counters()
    return {
        "partitions": partitions,
        "io": io._asdict() if io else {}
    }

def get_network_metrics():
    io = psutil.net_io_counters()
    return {
        "bytes_sent": io.bytes_sent,
        "bytes_recv": io.bytes_recv,
        "packets_sent": io.packets_sent,
        "packets_recv": io.packets_recv,
        "errin": io.errin,
        "errout": io.errout,
        "dropin": io.dropin,
        "dropout": io.dropout
    }

def collect_all_metrics():
    return {
        "timestamp": time.time(),
        "cpu": get_cpu_metrics(),
        "memory": get_memory_metrics(),
        "disk": get_disk_metrics(),
        "network": get_network_metrics()
    }
