import multiprocessing
import queue

def _worker(func, q, args, kwargs):
    """
    The target function executed inside the isolated process.
    Catches exceptions and passes them back through the queue.
    """
    try:
        result = func(*args, **kwargs)
        q.put(("SUCCESS", result))
    except Exception as e:
        q.put(("ERROR", e))
        
    try:
        q.close()
        import time
        time.sleep(0.2)
    except Exception:
        pass
        
    import os
    os._exit(0)

def run_with_timeout(func, args=(), kwargs=None, timeout_seconds=600):
    """
    Runs a target function in an isolated process with a strict timeout.
    If the function exceeds the timeout, the process is forcefully terminated
    and a TimeoutError is raised.
    
    This is highly useful for catching infinite loops in compiled C/Rust modules.
    Uses bounded join + forced kill to prevent Windows socket deadlocks on cleanup.
    """
    if kwargs is None:
        kwargs = {}
        
    q = multiprocessing.Queue()
    p = multiprocessing.Process(target=_worker, args=(func, q, args, kwargs))
    p.start()
    
    try:
        # Wait for the worker to finish, but strictly bound by the timeout
        status, result = q.get(timeout=timeout_seconds)
        
        # Bounded join: wait max 5 seconds for cleanup, then force-kill
        p.join(timeout=5)
        if p.is_alive():
            p.kill()
            p.join(timeout=2)
        
        if status == "SUCCESS":
            return result
        else:
            raise result # Raise the original exception caught in the worker
            
    except queue.Empty:
        # Timeout breached! Mercilessly kill the frozen worker process.
        print(f"[TIMEOUT TRIGGERED] The function '{func.__name__}' froze and exceeded {timeout_seconds} seconds. Terminating process...")
        p.terminate()
        p.join(timeout=5)
        if p.is_alive():
            p.kill()
            p.join(timeout=2)
        raise TimeoutError(f"Function {func.__name__} was forcibly terminated after {timeout_seconds} seconds.")

