"""
Decorator for timing stages
"""
import time

def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(seconds, 60)
    return f"{int(minutes)}m {secs:.0f}s"

def timed(label_fn):
    def decorator(fn):
        def wrapper(self, *args, **kwargs):
            start = time.perf_counter()
            result = fn(self, *args, **kwargs)
            print(f"{label_fn(self, *args, **kwargs)} done in {format_duration(time.perf_counter() - start)}")
            return result
        return wrapper
    return decorator