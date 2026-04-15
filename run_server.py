"""
Run the NSE Screener API server.
Usage: python run_server.py
"""

import uvicorn
import subprocess
import shutil


def start_ollama():
    """Auto-start Ollama if installed (for AI chat mode)."""
    if shutil.which("ollama"):
        try:
            # Check if already running
            import httpx
            r = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
            if r.status_code == 200:
                print("  Ollama already running")
                return
        except Exception:
            pass
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("  Ollama started in background")
        except Exception as e:
            print(f"  Ollama start failed: {e}")
    else:
        print("  Ollama not installed (AI chat will use Simple mode)")


if __name__ == "__main__":
    print("Starting YOINTELL server...")
    start_ollama()
    uvicorn.run(
        "api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
